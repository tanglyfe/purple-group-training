"""
SSF Aquatics — SwimCloud Scraper
Runs via GitHub Actions on a schedule.

What it does:
1. Scrapes the SSF team roster from SwimCloud (both M and F)
2. For each swimmer scrapes their full SCY times history (all meets, all events)
3. Derives best times and current-season history per event
4. Writes to Firestore — preserves historical data, only improves best times
5. Marks swimmers no longer on roster as inactive
"""

import os
import re
import json
import asyncio
from datetime import datetime, timezone

from playwright.async_api import async_playwright
from google.cloud import firestore
from google.oauth2 import service_account

# ── CONFIG ───────────────────────────────────────────────────────────────────
TEAM_ID      = "10000205"
TEAM_URL     = f"https://www.swimcloud.com/team/{TEAM_ID}/roster/"
SEASON_ID    = "29"    # 2025-2026
DELAY_SEC    = 1.5
MAX_RETRIES  = 3

# Season date bounds (2025-2026)
SEASON_START = datetime(2025, 9, 1, tzinfo=timezone.utc)
SEASON_END   = datetime(2026, 8, 31, tzinfo=timezone.utc)


# ── FIREBASE INIT ─────────────────────────────────────────────────────────────
def init_firestore():
    sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if not sa_json:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT env var not set")
    sa_info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(sa_info)
    return firestore.Client(project="ssfaquatics", credentials=creds)


# ── ROSTER SCRAPE ─────────────────────────────────────────────────────────────
async def scrape_roster(page) -> list[dict]:
    """Scrape full team roster for current season — both genders."""
    swimmers = []
    for gender in ["M", "F"]:
        url = f"{TEAM_URL}?gender={gender}&season_id={SEASON_ID}"
        print(f"  Fetching roster ({gender})...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1000)
        rows = await page.query_selector_all("table tbody tr")
        for row in rows:
            link = await row.query_selector("a[href*='/swimmer/']")
            if not link:
                continue
            href = await link.get_attribute("href")
            name = (await link.inner_text()).strip()
            m = re.search(r"/swimmer/(\d+)", href)
            if not m:
                continue
            swimmers.append({
                "swimcloudId": m.group(1),
                "name": name,
                "gender": gender,
            })
    print(f"  Found {len(swimmers)} swimmers total")
    return swimmers


# ── TIMES HISTORY SCRAPE ──────────────────────────────────────────────────────
async def scrape_times_history(page, swimmer_id: str) -> dict:
    """
    Scrape full SCY times history for a swimmer.

    Returns:
      {
        "50 Free": [
          { "time": "33.15", "secs": 33.15, "date": "2026-02-21", "meet": "Pacific 10&U" },
          ...
        ],
      }
    Sorted fastest first within each event.
    """
    url = f"https://www.swimcloud.com/swimmer/{swimmer_id}/times/?course=Y"

    for attempt in range(MAX_RETRIES):
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1000)

            try:
                await page.wait_for_selector("table", timeout=5000)
            except:
                return {}, None

            history = {}
            age_at_swim_samples = []  # list of (meet_date_str, age_int) to back-calc birth year
            rows = await page.query_selector_all("table tbody tr")

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    continue

                # Grab all cell text to find age-at-swim regardless of column order
                cell_texts = [(await c.inner_text()).strip() for c in cells]

                event_raw = cell_texts[0].replace("\n", " ")
                time_raw  = cell_texts[1] if len(cell_texts) > 1 else ""

                # Scan all cells for date and meet — look for date pattern and age
                date_str = ""
                meet_str = ""
                age_at_swim = None

                for i, txt in enumerate(cell_texts[2:], start=2):
                    if not txt:
                        continue
                    # Date: matches patterns like "Jan. 15, 2026" or "2026-01-15"
                    if re.search(r"\d{4}", txt) and re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\.|-)", txt, re.IGNORECASE):
                        if not date_str:
                            date_str = txt
                    # Age at swim: a standalone 1-2 digit number in range 5-22
                    elif re.match(r"^\d{1,2}$", txt):
                        val = int(txt)
                        if 5 <= val <= 22:
                            age_at_swim = val
                    # Meet name: longer text that's not a time or date
                    elif len(txt) > 5 and not re.match(r"^[\d:.]+$", txt) and not meet_str:
                        meet_str = txt

                if not time_raw or time_raw in ("–", "-", "NT"):
                    continue

                event = normalize_event(event_raw)
                if not event:
                    continue

                try:
                    secs = parse_time(time_raw)
                except:
                    continue

                parsed_date = parse_date(date_str)

                # Collect age samples for birth year estimation
                if age_at_swim and parsed_date:
                    age_at_swim_samples.append((parsed_date, age_at_swim))

                entry = {
                    "time": time_raw,
                    "secs": secs,
                    "date": parsed_date,
                    "meet": meet_str,
                }

                if event not in history:
                    history[event] = []
                history[event].append(entry)

            # Sort each event fastest first
            for event in history:
                history[event].sort(key=lambda x: x["secs"])

            # Estimate birth year from age-at-swim samples
            birth_year = estimate_birth_year(age_at_swim_samples)

            return history, birth_year

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"    Retry {attempt+1} for {swimmer_id}: {e}")
                await page.wait_for_timeout(2000)
            else:
                print(f"    Failed {swimmer_id}: {e}")
                return {}, None

    return {}, None


def parse_date(raw: str) -> str:
    """Try to parse a date string into YYYY-MM-DD. Returns '' on failure."""
    raw = raw.strip()
    if not raw:
        return ""
    for fmt in ("%b. %d, %Y", "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except:
            continue
    return raw


def normalize_event(raw: str) -> str | None:
    raw = raw.strip()
    m = re.match(r"(\d+)", raw)
    if not m:
        return None
    dist = m.group(1)
    r = raw.upper()
    if "FREE" in r:                                    stroke = "Free"
    elif "BACK" in r:                                  stroke = "Back"
    elif "BREAST" in r:                                stroke = "Breast"
    elif "FLY" in r or "BUTTERFLY" in r:               stroke = "Fly"
    elif "MEDLEY" in r or " IM" in r or r.endswith("IM"): stroke = "IM"
    else:                                              return None
    return f"{dist} {stroke}"


def parse_time(t: str) -> float:
    t = t.strip()
    if ":" in t:
        parts = t.split(":")
        return int(parts[0]) * 60 + float(parts[1])
    return float(t)


def is_this_season(date_str: str) -> bool:
    if not date_str:
        return False
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return SEASON_START <= d <= SEASON_END
    except:
        return False




def estimate_birth_year(samples: list[tuple[str, int]]) -> int | None:
    """
    Back-calculate birth year from (meet_date, age_at_swim) samples.

    USA Swimming age groups are based on age on the last day of the meet,
    so a swimmer listed as "12" swam the meet while still 12 years old.

    Strategy: for each sample, the swimmer's birth year is either
      meet_year - age  or  meet_year - age - 1
    depending on whether their birthday has passed yet in that year.
    We collect all candidate birth years and return the most common one.
    """
    if not samples:
        return None

    candidates = []
    for date_str, age in samples:
        try:
            meet_year = int(date_str[:4])
            # Birth year is meet_year - age (birthday already passed) or
            # meet_year - age - 1 (birthday hasn't passed yet in meet year)
            candidates.append(meet_year - age)
            candidates.append(meet_year - age - 1)
        except:
            continue

    if not candidates:
        return None

    # Most frequent candidate wins
    from collections import Counter
    counts = Counter(candidates)
    best = counts.most_common(1)[0][0]
    return best


def calc_age_from_birth_year(birth_year: int | None) -> int | None:
    """Calculate current age from birth year."""
    if not birth_year:
        return None
    return datetime.now(timezone.utc).year - birth_year

# ── FIRESTORE WRITE ───────────────────────────────────────────────────────────
def sync_to_firestore(db, scraped_swimmers: list[dict], history_map: dict, birth_year_map: dict = None):
    """
    Firestore structure per swimmer doc:

      times: { "50 Free": "33.15", ... }
        — All-time best per event

      season_history: {
        "50 Free": [
          { time, secs, date, meet },  ← sorted fastest first
          ...
        ]
      }
        — This season (2025-2026) entries only
    """
    swimmers_ref = db.collection("swimmers")
    current_ids  = {s["swimcloudId"] for s in scraped_swimmers}

    deactivated = 0
    for doc in swimmers_ref.where("active", "==", True).stream():
        if doc.id not in current_ids:
            swimmers_ref.document(doc.id).update({
                "active": False,
                "deactivatedAt": datetime.now(timezone.utc),
            })
            deactivated += 1
            print(f"  Deactivated: {doc.to_dict().get('name', doc.id)}")

    updated = new_count = 0
    for swimmer in scraped_swimmers:
        sid     = swimmer["swimcloudId"]
        history = history_map.get(sid, {})

        # All-time best times
        best_times = {ev: entries[0]["time"] for ev, entries in history.items() if entries}

        # This season history only
        season_history = {}
        for event, entries in history.items():
            season_entries = [
                {"time": e["time"], "secs": e["secs"], "date": e["date"], "meet": e["meet"]}
                for e in entries if is_this_season(e["date"])
            ]
            if season_entries:
                season_history[event] = season_entries

        ref  = swimmers_ref.document(sid)
        snap = ref.get()

        if snap.exists:
            existing_best = snap.to_dict().get("times", {})
            merged = dict(existing_best)
            for event, t in best_times.items():
                if event not in merged or parse_time(t) < parse_time(merged[event]):
                    merged[event] = t
            birth_year = (birth_year_map or {}).get(sid)
            ref.update({
                "name":           swimmer["name"],
                "gender":         swimmer["gender"],
                "active":         True,
                "birthYear":      birth_year,
                "age":            calc_age_from_birth_year(birth_year),
                "times":          merged,
                "season_history": season_history,
                "lastUpdated":    datetime.now(timezone.utc),
            })
            updated += 1
        else:
            birth_year = (birth_year_map or {}).get(sid)
            ref.set({
                "swimcloudId":    sid,
                "name":           swimmer["name"],
                "gender":         swimmer["gender"],
                "active":         True,
                "birthYear":      birth_year,
                "age":            calc_age_from_birth_year(birth_year),
                "times":          best_times,
                "season_history": season_history,
                "createdAt":      datetime.now(timezone.utc),
                "lastUpdated":    datetime.now(timezone.utc),
            })
            new_count += 1

    print(f"\n  ✓ {new_count} new  |  {updated} updated  |  {deactivated} deactivated")


# ── MAIN ──────────────────────────────────────────────────────────────────────
async def main():
    print("=== SSF Aquatics SwimCloud Scraper ===")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}\n")

    db = init_firestore()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print("Step 1: Scraping roster...")
        swimmers = await scrape_roster(page)

        print(f"\nStep 2: Scraping times history for {len(swimmers)} swimmers...")
        history_map = {}
        birth_year_map = {}

        for i, swimmer in enumerate(swimmers, 1):
            sid  = swimmer["swimcloudId"]
            name = swimmer["name"]
            print(f"  [{i}/{len(swimmers)}] {name}")

            history, birth_year = await scrape_times_history(page, sid)
            history_map[sid] = history
            birth_year_map[sid] = birth_year

            if history:
                season_count = sum(
                    1 for ev in history
                    if any(is_this_season(e["date"]) for e in history[ev])
                )
                by = birth_year_map.get(sid)
                age_str = f", estimated age {calc_age_from_birth_year(by)} (b.{by})" if by else ""
                print(f"    → {len(history)} events, {season_count} with season data{age_str}")
            else:
                print(f"    → No times found")

            if i < len(swimmers):
                await page.wait_for_timeout(int(DELAY_SEC * 1000))

        await browser.close()

    print("\nStep 3: Syncing to Firestore...")
    sync_to_firestore(db, swimmers, history_map, birth_year_map)

    print(f"\n=== Done: {datetime.now(timezone.utc).isoformat()} ===")


if __name__ == "__main__":
    asyncio.run(main())

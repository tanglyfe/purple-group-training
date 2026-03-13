"""
SSF Aquatics — SwimCloud Scraper
Runs via GitHub Actions on a schedule.

What it does:
1. Scrapes the SSF team roster from SwimCloud (both M and F)
2. For each active swimmer, scrapes all their best SCY times
3. Writes roster + times to Firestore
4. Marks swimmers no longer on SwimCloud roster as inactive
   (preserves their data — just hides them from site views)
"""

import os
import re
import time
import json
import asyncio
from datetime import datetime, timezone

from playwright.async_api import async_playwright
from google.cloud import firestore
from google.oauth2 import service_account

# ── CONFIG ──────────────────────────────────────────────────────────────────
TEAM_ID      = "10000205"
TEAM_URL     = f"https://www.swimcloud.com/team/{TEAM_ID}/roster/"
SEASON_ID    = "29"   # 2025-2026
DELAY_SEC    = 1.5    # polite delay between swimmer requests
MAX_RETRIES  = 3

# ── FIREBASE INIT ────────────────────────────────────────────────────────────
def init_firestore():
    sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if not sa_json:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT env var not set")
    sa_info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(sa_info)
    return firestore.Client(project="ssfaquatics", credentials=creds)


# ── ROSTER SCRAPE ────────────────────────────────────────────────────────────
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
            # Name cell contains a link to /swimmer/{id}
            link = await row.query_selector("a[href*='/swimmer/']")
            if not link:
                continue
            href = await link.get_attribute("href")
            name = (await link.inner_text()).strip()
            swimmer_id = re.search(r"/swimmer/(\d+)", href)
            if not swimmer_id:
                continue
            swimmers.append({
                "swimcloudId": swimmer_id.group(1),
                "name": name,
                "gender": gender,
            })

    print(f"  Found {len(swimmers)} swimmers total")
    return swimmers


# ── BEST TIMES SCRAPE ────────────────────────────────────────────────────────
async def scrape_best_times(page, swimmer_id: str) -> dict:
    """
    Scrape all SCY best times for a swimmer.
    Returns dict keyed by event name e.g. {"50 Y Free": "33.15", ...}
    """
    url = f"https://www.swimcloud.com/swimmer/{swimmer_id}/times/?course=Y"

    for attempt in range(MAX_RETRIES):
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(800)

            # Wait for times table to appear (may not exist for new swimmers)
            try:
                await page.wait_for_selector("table", timeout=5000)
            except:
                return {}  # No times yet

            # Grab all table rows — each row is one event
            times = {}
            rows = await page.query_selector_all("table tbody tr")

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    continue

                event_cell = await cells[0].inner_text()
                time_cell  = await cells[1].inner_text()

                event = event_cell.strip().replace("\n", " ")
                t     = time_cell.strip()

                # Skip empty or placeholder times
                if not t or t == "–" or t == "-":
                    continue

                # Normalize event name — e.g. "50 Free" → "50 Y Free"
                event = normalize_event(event)
                if event:
                    times[event] = t

            return times

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"    Retry {attempt + 1} for swimmer {swimmer_id}: {e}")
                await page.wait_for_timeout(2000)
            else:
                print(f"    Failed to scrape swimmer {swimmer_id}: {e}")
                return {}

    return {}


def normalize_event(raw: str) -> str | None:
    """
    Normalize SwimCloud event names to a consistent format.
    e.g. "50 Free", "50 Freestyle", "50 Y Freestyle" → "50 Free"
         "100 Back" → "100 Back"
         "200 IM", "200 Individual Medley" → "200 IM"
    Returns None if unrecognized.
    """
    raw = raw.strip()

    # Extract distance
    dist_match = re.match(r"(\d+)", raw)
    if not dist_match:
        return None
    dist = dist_match.group(1)

    r = raw.upper()

    if "FREE" in r:   stroke = "Free"
    elif "BACK" in r: stroke = "Back"
    elif "BREAST" in r: stroke = "Breast"
    elif "FLY" in r or "BUTTERFLY" in r: stroke = "Fly"
    elif "MEDLEY" in r or " IM" in r or r.endswith("IM"): stroke = "IM"
    else:
        return None

    return f"{dist} {stroke}"


# ── FIRESTORE WRITE ───────────────────────────────────────────────────────────
def sync_to_firestore(db, scraped_swimmers: list[dict], times_map: dict[str, dict]):
    """
    Sync scraped data to Firestore.

    Firestore structure:
      swimmers/{swimcloudId}
        name, gender, swimcloudId, active, lastUpdated
        times: { "50 Free": "33.15", "100 Free": "1:17.68", ... }

    Swimmers no longer on roster → marked active=False (data preserved).
    """
    swimmers_ref = db.collection("swimmers")

    # Build set of current swimcloud IDs
    current_ids = {s["swimcloudId"] for s in scraped_swimmers}

    # Mark removed swimmers inactive
    existing = swimmers_ref.where("active", "==", True).stream()
    deactivated = 0
    for doc in existing:
        if doc.id not in current_ids:
            swimmers_ref.document(doc.id).update({
                "active": False,
                "deactivatedAt": datetime.now(timezone.utc)
            })
            deactivated += 1
            print(f"  Deactivated: {doc.to_dict().get('name', doc.id)}")

    # Upsert active swimmers
    updated = 0
    new_count = 0
    for swimmer in scraped_swimmers:
        sid   = swimmer["swimcloudId"]
        times = times_map.get(sid, {})
        ref   = swimmers_ref.document(sid)
        snap  = ref.get()

        if snap.exists:
            existing_data  = snap.to_dict()
            existing_times = existing_data.get("times", {})

            # Merge times — only keep improvements (lower time = better)
            merged = dict(existing_times)
            for event, new_time in times.items():
                if event not in merged or time_is_faster(new_time, merged[event]):
                    merged[event] = new_time

            ref.update({
                "name":        swimmer["name"],
                "gender":      swimmer["gender"],
                "active":      True,
                "times":       merged,
                "lastUpdated": datetime.now(timezone.utc),
            })
            updated += 1
        else:
            ref.set({
                "swimcloudId": sid,
                "name":        swimmer["name"],
                "gender":      swimmer["gender"],
                "active":      True,
                "times":       times,
                "createdAt":   datetime.now(timezone.utc),
                "lastUpdated": datetime.now(timezone.utc),
            })
            new_count += 1

    print(f"\n  ✓ {new_count} new swimmers added")
    print(f"  ✓ {updated} swimmers updated")
    print(f"  ✓ {deactivated} swimmers deactivated")


def time_is_faster(new_time: str, old_time: str) -> bool:
    """Compare swim times as seconds. Returns True if new_time is faster (lower)."""
    try:
        return parse_time(new_time) < parse_time(old_time)
    except:
        return False


def parse_time(t: str) -> float:
    """Convert time string to seconds. Handles 'SS.ss' and 'M:SS.ss'."""
    t = t.strip()
    if ":" in t:
        parts = t.split(":")
        return int(parts[0]) * 60 + float(parts[1])
    return float(t)


# ── MAIN ─────────────────────────────────────────────────────────────────────
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

        # 1. Scrape roster
        print("Step 1: Scraping roster...")
        swimmers = await scrape_roster(page)

        # 2. Scrape times for each swimmer
        print(f"\nStep 2: Scraping times for {len(swimmers)} swimmers...")
        times_map = {}

        for i, swimmer in enumerate(swimmers, 1):
            sid  = swimmer["swimcloudId"]
            name = swimmer["name"]
            print(f"  [{i}/{len(swimmers)}] {name} (id: {sid})")

            times = await scrape_best_times(page, sid)
            times_map[sid] = times

            if times:
                print(f"    → {len(times)} events: {', '.join(list(times.keys())[:5])}{'...' if len(times) > 5 else ''}")
            else:
                print(f"    → No times found")

            # Polite delay
            if i < len(swimmers):
                await page.wait_for_timeout(int(DELAY_SEC * 1000))

        await browser.close()

    # 3. Sync to Firestore
    print("\nStep 3: Syncing to Firestore...")
    sync_to_firestore(db, swimmers, times_map)

    print(f"\n=== Done: {datetime.now(timezone.utc).isoformat()} ===")


if __name__ == "__main__":
    asyncio.run(main())

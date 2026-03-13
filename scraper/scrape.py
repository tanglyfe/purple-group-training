name: SwimCloud Scraper

on:
  # Run every Sunday at 2am UTC (6pm Saturday PST)
  schedule:
    - cron: '0 2 * * 0'

  # Also allow manual trigger from GitHub Actions tab
  workflow_dispatch:

jobs:
  scrape:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install -r scraper/requirements.txt
          playwright install chromium
          playwright install-deps chromium

      - name: Run scraper
        env:
          FIREBASE_SERVICE_ACCOUNT: ${{ secrets.FIREBASE_SERVICE_ACCOUNT }}
        run: |
          python scraper/scrape.py

      - name: Upload log on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: scraper-failure-log
          path: scraper/*.log
          retention-days: 7

#!/usr/bin/env python3
"""
scripts/build_ppc.py
Builds paid-media/index.html from:
  1. PPC Google Sheet      — raw_campaign_daily (Google Ads data exported by script)
  2. Colleague's Sheet     — Bing Ads weekly data (transposed layout)
  3. Amplitude Sheet       — free sign-up counts by week

Usage (local dev):
  set GA4_CREDENTIALS_FILE=C:/Users/mattj/Downloads/visme-marketing-491309-47059dacd5b9.json
  python scripts/build_ppc.py
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.sheets_client import (
    fetch_google_ads_from_sheet,
    fetch_bing_weekly,
    fetch_amplitude_data,
)
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "paid-media", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "paid-media", "index.html")

GOOGLE_ADS_SHEET_ID = os.environ.get(
    "GOOGLE_ADS_SHEET_ID",
    "11YiWr1aHhwBto9JrgwnSGJLtyq1KEfJvs5ZRbkoWKho",
)
COLLEAGUE_SHEET_ID = os.environ.get(
    "COLLEAGUE_PPC_SHEET_ID",
    "1dvV2lkAbAT9kJLEB2At_0AG8emEhhe5jmubzscKw-uY",
)
AMPLITUDE_SHEET_ID = os.environ.get(
    "AMPLITUDE_SHEET_ID",
    "11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw",
)


def main():
    print("=" * 60)
    print("Building paid-media/index.html (v2)")
    print("=" * 60)

    # ── 1. Google Ads (from sheet) ─────────────────────────────────────────────
    try:
        google_data = fetch_google_ads_from_sheet(GOOGLE_ADS_SHEET_ID)
    except Exception as e:
        print(f"  WARNING: Google Ads sheet failed: {e}")
        google_data = {
            "weekly": [], "camps": [], "ads": [], "kw": [],
            "kw_weekly": [], "geo": {}, "budgets": {},
            "build_date": date.today().isoformat(),
        }

    # ── 2. Bing Ads ────────────────────────────────────────────────────────────
    print("Bing Ads: reading sheet...")
    try:
        bing_list    = fetch_bing_weekly(COLLEAGUE_SHEET_ID)
        bing_by_week = {r["week_start"]: r for r in bing_list}
        print(f"  -> {len(bing_list)} Bing weeks")
    except Exception as e:
        print(f"  WARNING: Bing sheet failed: {e}")
        bing_by_week = {}

    # ── 3. Amplitude ───────────────────────────────────────────────────────────
    print("Amplitude: signups...")
    try:
        amp_data    = fetch_amplitude_data(AMPLITUDE_SHEET_ID)
        amp_by_week = {w: amp_data["signups"].get(w, 0) for w in amp_data.get("weeks", [])}
        print(f"  -> {len(amp_by_week)} Amplitude weeks")
    except Exception as e:
        print(f"  WARNING: Amplitude failed: {e}")
        amp_by_week = {}

    # ── 4. Merge WEEKLY ────────────────────────────────────────────────────────
    merged_weekly = []
    for gw in google_data["weekly"]:
        ws = gw["week_start"]
        bw = bing_by_week.get(ws, {})
        merged_weekly.append({
            "week_start":     gw["week_start"],
            "week_end":       gw["week_end"],
            "label":          gw["label"],
            "g_spend":        gw["g_spend"],
            "g_clicks":       gw["g_clicks"],
            "g_impressions":  gw["g_impressions"],
            "g_conversions":  gw["g_conversions"],
            "m_spend":        bw.get("m_spend",        0.0),
            "m_clicks":       bw.get("m_clicks",        0),
            "m_impressions":  bw.get("m_impressions",   0),
            "m_conversions":  bw.get("m_conversions",   0.0),
            "m_ctr":          bw.get("m_ctr",           0.0),
            "m_free_signups": bw.get("m_free_signups",  0),
            "ga4_new_users":  amp_by_week.get(ws, 0),
        })

    # ── 5. Inject ──────────────────────────────────────────────────────────────
    inject_data(
        template_path=TEMPLATE,
        data_dict={
            "WEEKLY":     merged_weekly,
            "CAMPS_G":    google_data["camps"],
            "CAMPS_M":    [],
            "ADS_G":      google_data["ads"],
            "ADS_M":      [],
            "KW_G":       google_data["kw"],
            "KW_M":       [],
            "KW_G_W":     google_data["kw_weekly"],
            "KW_M_W":     [],
            "GEO":        google_data["geo"],   # flat array [{state, g_cost, ...}]
            "BUDGETS":    google_data["budgets"],
            "MS_ENABLED": False,
            "BUILD_DATE": date.today().isoformat(),
        },
        output_path=OUTPUT,
    )


if __name__ == "__main__":
    main()

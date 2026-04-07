#!/usr/bin/env python3
"""
scripts/build_ppc.py
Builds paid-media/index.html from:
  1. Google Ads API        — spend, clicks, conv, campaigns, ads, keywords, geo
  2. Colleague's Sheet     — Bing Ads weekly data (transposed layout)
  3. Amplitude Sheet       — free sign-up counts by week

Usage (local dev):
  set GA4_CREDENTIALS_FILE=C:\Users\mattj\Downloads\visme-marketing-491309-47059dacd5b9.json
  set GOOGLE_ADS_DEVELOPER_TOKEN=<token>
  python scripts/build_ppc.py
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.google_ads_client import fetch_all_google_ads, _resolve_credentials_file
from scripts.shared.sheets_client import fetch_bing_weekly, fetch_amplitude_data
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "paid-media", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "paid-media", "index.html")

DEVELOPER_TOKEN    = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "")
CUSTOMER_ID        = os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "2405880186")
MANAGER_ID         = os.environ.get("GOOGLE_ADS_MANAGER_ID",  "4091490058")
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

    credentials_file = _resolve_credentials_file()

    # ── 1. Google Ads ──────────────────────────────────────────────────────────
    if not DEVELOPER_TOKEN:
        print("⚠️  GOOGLE_ADS_DEVELOPER_TOKEN not set — Google Ads sections will be empty")
        google_data = {
            "weekly": [], "camps": [], "ads": [], "kw": [],
            "kw_weekly": [], "geo": {}, "budgets": {},
            "build_date": date.today().isoformat(),
        }
    else:
        google_data = fetch_all_google_ads(
            developer_token=DEVELOPER_TOKEN,
            credentials_file=credentials_file,
            manager_id=MANAGER_ID,
            customer_id=CUSTOMER_ID,
        )

    # ── 2. Bing Ads ────────────────────────────────────────────────────────────
    print("⏳ Bing Ads: reading sheet...")
    try:
        bing_list    = fetch_bing_weekly(COLLEAGUE_SHEET_ID)
        bing_by_week = {r["week_start"]: r for r in bing_list}
        print(f"  → {len(bing_list)} Bing weeks")
    except Exception as e:
        print(f"  ⚠️  Bing sheet failed: {e}")
        bing_by_week = {}

    # ── 3. Amplitude ───────────────────────────────────────────────────────────
    print("⏳ Amplitude: signups...")
    try:
        amp_data    = fetch_amplitude_data(AMPLITUDE_SHEET_ID)
        amp_by_week = {w: amp_data["signups"].get(w, 0) for w in amp_data.get("weeks", [])}
        print(f"  → {len(amp_by_week)} Amplitude weeks")
    except Exception as e:
        print(f"  ⚠️  Amplitude failed: {e}")
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
            "GEO":        google_data["geo"],
            "BUDGETS":    google_data["budgets"],
            "MS_ENABLED": False,
            "BUILD_DATE": date.today().isoformat(),
        },
        output_path=OUTPUT,
    )


if __name__ == "__main__":
    main()

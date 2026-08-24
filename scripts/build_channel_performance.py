#!/usr/bin/env python3
"""
scripts/build_channel_performance.py
Fetches live GA4 channel x source/medium session data, plus Free/Paid from
two Google Sheets — weekly (Week mode) and monthly (Month mode) — joined to
GA4 channels by scripts/shared/title_classifier.py, and injects it all into
channel-performance/index.html.

Usage:
    python scripts/build_channel_performance.py

Environment variables:
    GA4_CREDENTIALS_JSON            JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE            Path to service account JSON file (local dev)
    GA4_PROPERTY_ID                 GA4 property ID (default: 368188880)
    CHANNEL_PERF_SHEET_ID           "Weekly Conversion & Signups channels" sheet
                                     (default: 1F6h9jAVy7SEHiF1jS_HkFZ6Htu5fYJ-Q8yQxe0iJvCI)
    CHANNEL_PERF_MONTHLY_SHEET_ID   "Conversions / signups, monthly" sheet
                                     (default: 1JX0FMCDhhOlV4yEUW9vk9_BZqusKwNOGimcoYoJujzw)

Month mode's Free/Paid come from the monthly sheet directly (true calendar-
month granularity), NOT derived from the weekly sheet — per direct
instruction, since the two sheets don't reconcile exactly.

The service account (visme-dashboards@visme-marketing-491309.iam
.gserviceaccount.com) must be granted at least Viewer access on BOTH sheets.
Each fetch fails independently and gracefully — a problem with one sheet
ships that half as unavailable ("—") without blocking the other, GA4
Traffic, or any other dashboard's weekly rebuild (see README.md and
.github/workflows/build.yml's continue-on-error note on this step).
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.ga4_client import fetch_channel_performance_data
from scripts.shared.sheets_client import (
    fetch_channel_conversions_data, CHANNEL_PERF_SHEET_ID,
    fetch_channel_conversions_monthly_data, CHANNEL_PERF_MONTHLY_SHEET_ID,
)
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "channel-performance", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "channel-performance", "index.html")


def main():
    print("=" * 60)
    print("Building channel-performance/index.html")
    print("=" * 60)

    property_id = os.environ.get("GA4_PROPERTY_ID", "368188880")
    week_sheet_id = os.environ.get("CHANNEL_PERF_SHEET_ID", CHANNEL_PERF_SHEET_ID)
    month_sheet_id = os.environ.get("CHANNEL_PERF_MONTHLY_SHEET_ID", CHANNEL_PERF_MONTHLY_SHEET_ID)

    print("\n[1/3] Fetching GA4 traffic by channel...")
    cp_data = fetch_channel_performance_data(property_id=property_id)

    unclassified, referral = {}, {}

    print("\n[2/3] Fetching Week-mode Free/Paid from the weekly conversion sheet...")
    try:
        week_conv = fetch_channel_conversions_data(sheet_id=week_sheet_id)
        cp_data["weeklyConversions"] = week_conv["weeklyConversions"]
        cp_data["weekConversionsUnavailable"] = False
        unclassified.update(week_conv["unclassifiedTitles"])
        referral.update(week_conv["referralTitles"])
    except Exception:
        print("  ⚠️  Could not fetch the weekly conversion sheet — Week mode Free/Paid "
              "will show as unavailable for this build. Likely cause: the service "
              "account has not been granted access to the sheet yet. Full error:")
        traceback.print_exc()
        cp_data["weeklyConversions"] = {}
        cp_data["weekConversionsUnavailable"] = True

    print("\n[3/3] Fetching Month-mode Free/Paid from the monthly conversion sheet...")
    try:
        month_conv = fetch_channel_conversions_monthly_data(sheet_id=month_sheet_id)
        cp_data["monthlyConversions"] = month_conv["monthlyConversions"]
        cp_data["monthConversionsUnavailable"] = False
        unclassified.update(month_conv["unclassifiedTitles"])
        referral.update(month_conv["referralTitles"])
    except Exception:
        print("  ⚠️  Could not fetch the monthly conversion sheet — Month mode Free/Paid "
              "will show as unavailable for this build. Likely cause: the service "
              "account has not been granted access to the sheet yet. Full error:")
        traceback.print_exc()
        cp_data["monthlyConversions"] = {}
        cp_data["monthConversionsUnavailable"] = True

    cp_data["unclassifiedTitles"] = unclassified
    cp_data["referralTitles"] = referral

    inject_data(
        template_path=TEMPLATE,
        data_dict={"CP": cp_data},
        output_path=OUTPUT,
    )
    print("Done.")


if __name__ == "__main__":
    main()

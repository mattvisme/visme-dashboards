#!/usr/bin/env python3
"""
scripts/build_channel_performance.py
Fetches live GA4 channel x source/medium session data, plus Free/Paid from
the "Weekly Conversion & Signups channels" Google Sheet (joined to GA4
channels by scripts/shared/title_classifier.py), and injects both into
channel-performance/index.html.

Usage:
    python scripts/build_channel_performance.py

Environment variables:
    GA4_CREDENTIALS_JSON    JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE    Path to service account JSON file (local dev)
    GA4_PROPERTY_ID         GA4 property ID (default: 368188880)
    CHANNEL_PERF_SHEET_ID   "Weekly Conversion & Signups channels" sheet ID
                            (default: 1F6h9jAVy7SEHiF1jS_HkFZ6Htu5fYJ-Q8yQxe0iJvCI)

The service account (visme-dashboards@visme-marketing-491309.iam
.gserviceaccount.com) must be granted at least Viewer access on the
CHANNEL_PERF_SHEET_ID spreadsheet directly. If that access is missing (or
the sheet fetch fails for any other reason), this script does NOT fail the
whole build — it logs the error and ships Traffic-only data instead, so a
Sheets problem never blocks GA4 traffic from updating. See README.md and
.github/workflows/build.yml's continue-on-error note on this step for the
matching protection at the workflow level (a failure here must not block
every OTHER dashboard's weekly rebuild either).
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.ga4_client import fetch_channel_performance_data
from scripts.shared.sheets_client import fetch_channel_conversions_data, CHANNEL_PERF_SHEET_ID
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "channel-performance", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "channel-performance", "index.html")


def main():
    print("=" * 60)
    print("Building channel-performance/index.html")
    print("=" * 60)

    property_id = os.environ.get("GA4_PROPERTY_ID", "368188880")
    sheet_id = os.environ.get("CHANNEL_PERF_SHEET_ID", CHANNEL_PERF_SHEET_ID)

    print("\n[1/2] Fetching GA4 traffic by channel...")
    cp_data = fetch_channel_performance_data(property_id=property_id)

    print("\n[2/2] Fetching Free/Paid from the Weekly Conversion & Signups sheet...")
    try:
        conv_data = fetch_channel_conversions_data(sheet_id=sheet_id)
        cp_data["weeklyConversions"] = conv_data["weeklyConversions"]
        cp_data["monthlyConversions"] = conv_data["monthlyConversions"]
        cp_data["unclassifiedTitles"] = conv_data["unclassifiedTitles"]
        cp_data["referralTitles"] = conv_data["referralTitles"]
        cp_data["conversionsUnavailable"] = False
    except Exception:
        print("  ⚠️  Could not fetch the conversion sheet — shipping Traffic-only "
              "data for this build. Likely cause: the service account has not "
              "been granted access to the sheet yet. Full error:")
        traceback.print_exc()
        cp_data["weeklyConversions"] = {}
        cp_data["monthlyConversions"] = {}
        cp_data["unclassifiedTitles"] = {}
        cp_data["referralTitles"] = {}
        cp_data["conversionsUnavailable"] = True

    inject_data(
        template_path=TEMPLATE,
        data_dict={"CP": cp_data},
        output_path=OUTPUT,
    )
    print("Done.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
scripts/build_executive.py
Fetches GA4, HubSpot, and Amplitude data and injects all three into
executive/index.html template.

Usage:
    python scripts/build_executive.py

Environment variables:
    GA4_CREDENTIALS_JSON   JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE   Path to service account JSON file (local dev)
    GA4_PROPERTY_ID        GA4 property ID (default: 368188880)
    HUBSPOT_SHEET_ID       Google Sheet ID for HubSpot data
    AMPLITUDE_SHEET_ID     Google Sheet ID for Amplitude data
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.ga4_client import fetch_ga4_data
from scripts.shared.sheets_client import fetch_hubspot_data, fetch_amplitude_data
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "executive", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "executive", "index.html")


def main():
    print("=" * 60)
    print("Building executive/index.html")
    print("=" * 60)

    property_id = os.environ.get("GA4_PROPERTY_ID", "368188880")
    hs_sheet_id = os.environ.get("HUBSPOT_SHEET_ID",
                                 "1TsDySDrmgSQEUjunQg77twgUS1fGgZIC71IbX-bAz1s")
    amp_sheet_id = os.environ.get("AMPLITUDE_SHEET_ID",
                                  "11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw")

    print("\n[1/3] Fetching GA4 sessions data…")
    ga4_data = fetch_ga4_data(property_id=property_id)

    print("\n[2/3] Fetching HubSpot data…")
    hs_data = fetch_hubspot_data(sheet_id=hs_sheet_id)

    print("\n[3/3] Fetching Amplitude data…")
    amp_data = fetch_amplitude_data(sheet_id=amp_sheet_id)

    print("\nInjecting all data into template…")
    inject_data(
        template_path=TEMPLATE,
        data_dict={
            "GA4": ga4_data,
            "AMP": amp_data,
            "HS":  hs_data,
        },
        output_path=OUTPUT,
    )
    print("Done.")


if __name__ == "__main__":
    main()

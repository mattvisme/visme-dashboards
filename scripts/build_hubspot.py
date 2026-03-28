#!/usr/bin/env python3
"""
scripts/build_hubspot.py
Reads HubSpot Google Sheet and injects data into hubspot/index.html template.

Usage:
    python scripts/build_hubspot.py

Environment variables:
    GA4_CREDENTIALS_JSON   JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE   Path to service account JSON file (local dev)
    HUBSPOT_SHEET_ID       Google Sheet ID for HubSpot data
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.sheets_client import fetch_hubspot_data
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "hubspot", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "hubspot", "index.html")


def main():
    print("=" * 60)
    print("Building hubspot/index.html")
    print("=" * 60)

    sheet_id = os.environ.get("HUBSPOT_SHEET_ID",
                              "1TsDySDrmgSQEUjunQg77twgUS1fGgZIC71IbX-bAz1s")
    hs_data = fetch_hubspot_data(sheet_id=sheet_id)

    inject_data(
        template_path=TEMPLATE,
        data_dict={"HS": hs_data},
        output_path=OUTPUT,
    )
    print("Done.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
scripts/build_gsc.py
Reads GSC data from Google Sheets (populated by the GSC Apps Script exporter)
and injects it into gsc/index.html.

Usage:
    python scripts/build_gsc.py

Environment variables:
    GA4_CREDENTIALS_JSON   JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE   Path to service account JSON file (local dev)
    GSC_SHEET_ID           Google Sheet ID for GSC data
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.sheets_client import fetch_gsc_sheet_data
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "gsc", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "gsc", "index.html")


def main():
    print("=" * 60)
    print("Building gsc/index.html")
    print("=" * 60)

    sheet_id = os.environ.get("GSC_SHEET_ID", "")
    if not sheet_id:
        print("ERROR: GSC_SHEET_ID environment variable is not set.")
        sys.exit(1)

    gsc_data = fetch_gsc_sheet_data(sheet_id=sheet_id)

    inject_data(
        template_path=TEMPLATE,
        data_dict={"D": gsc_data},
        output_path=OUTPUT,
    )
    print("Done.")


if __name__ == "__main__":
    main()

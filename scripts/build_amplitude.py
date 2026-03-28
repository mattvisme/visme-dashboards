#!/usr/bin/env python3
"""
scripts/build_amplitude.py
Reads Amplitude Google Sheet and injects data into amplitude/index.html template.

Usage:
    python scripts/build_amplitude.py

Environment variables:
    GA4_CREDENTIALS_JSON   JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE   Path to service account JSON file (local dev)
    AMPLITUDE_SHEET_ID     Google Sheet ID for Amplitude data
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.sheets_client import fetch_amplitude_data
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "amplitude", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "amplitude", "index.html")


def main():
    print("=" * 60)
    print("Building amplitude/index.html")
    print("=" * 60)

    sheet_id = os.environ.get("AMPLITUDE_SHEET_ID",
                              "11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw")
    amp_data = fetch_amplitude_data(sheet_id=sheet_id)

    inject_data(
        template_path=TEMPLATE,
        data_dict={"AMP": amp_data},
        output_path=OUTPUT,
    )
    print("Done.")


if __name__ == "__main__":
    main()

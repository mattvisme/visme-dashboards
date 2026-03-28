#!/usr/bin/env python3
"""
scripts/build_ga4.py
Fetches GA4 data and injects it into the ga4/index.html template.

Usage:
    python scripts/build_ga4.py

Environment variables:
    GA4_CREDENTIALS_JSON   JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE   Path to service account JSON file (local dev)
    GA4_PROPERTY_ID        GA4 property ID (default: 368188880)
"""

import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.ga4_client import fetch_ga4_data
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "ga4", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "ga4", "index.html")


def main():
    print("=" * 60)
    print("Building ga4/index.html")
    print("=" * 60)

    property_id = os.environ.get("GA4_PROPERTY_ID", "368188880")
    ga4_data = fetch_ga4_data(property_id=property_id)

    inject_data(
        template_path=TEMPLATE,
        data_dict={"GA4": ga4_data},
        output_path=OUTPUT,
    )
    print("Done.")


if __name__ == "__main__":
    main()

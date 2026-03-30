#!/usr/bin/env python3
"""
scripts/build_ppc.py
Reads PPC Google Sheet (raw campaign + conversion data) and Amplitude sheet
(for free sign-ups), aggregates into weekly metrics, and injects into
paid-media/index.html template.

Usage:
    python scripts/build_ppc.py

Environment variables:
    GA4_CREDENTIALS_JSON   JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE   Path to service account JSON file (local dev)
    PPC_SHEET_ID           Google Sheet ID for PPC data
                           (default: 11YiWr1aHhwBto9JrgwnSGJLtyq1KEfJvs5ZRbkoWKho)
    AMPLITUDE_SHEET_ID     Google Sheet ID for Amplitude data
                           (default: 11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.sheets_client import fetch_ppc_data, fetch_amplitude_data
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "paid-media", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "paid-media", "index.html")


def main():
    print("=" * 60)
    print("Building paid-media/index.html")
    print("=" * 60)

    ppc_sheet_id = os.environ.get("PPC_SHEET_ID",
                                   "11YiWr1aHhwBto9JrgwnSGJLtyq1KEfJvs5ZRbkoWKho")
    amp_sheet_id = os.environ.get("AMPLITUDE_SHEET_ID",
                                   "11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw")

    # Fetch PPC metrics (spend, clicks, ctr, convs, cpc, revenue)
    print("\n[1/2] Fetching PPC data…")
    ppc_payload = fetch_ppc_data(sheet_id=ppc_sheet_id)

    # Fetch Amplitude data for free sign-up counts
    print("\n[2/2] Fetching Amplitude sign-up data…")
    amp_data = fetch_amplitude_data(sheet_id=amp_sheet_id)

    # Build week → signups lookup from Amplitude and merge into PPC payload
    amp_signups = amp_data.get("signups", {})
    ppc_payload["signups"] = {
        w: amp_signups.get(w, 0)
        for w in ppc_payload["weeks"]
    }

    signups_matched = sum(1 for w in ppc_payload["weeks"] if amp_signups.get(w))
    print(f"\n  Signups matched for {signups_matched}/{len(ppc_payload['weeks'])} PPC weeks")

    # Inject into template
    inject_data(
        template_path=TEMPLATE,
        data_dict={"D": ppc_payload},
        output_path=OUTPUT,
    )
    print("Done.")


if __name__ == "__main__":
    main()

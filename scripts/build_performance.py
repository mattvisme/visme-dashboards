#!/usr/bin/env python3
"""
scripts/build_performance.py
Fetches HubSpot Fibbler (LinkedIn engagement) and contact acquisition data,
then injects it into performance/index.html.

Usage:
    python scripts/build_performance.py

Environment variables:
    HUBSPOT_ACCESS_TOKEN   HubSpot Private App token with scopes:
                               crm.objects.companies.read
                               crm.objects.contacts.read
                           ⚠️  This secret must be added to the GitHub
                               repository's Settings → Secrets and variables
                               → Actions before the CI build step will work.
                               It is NOT the same as HUBSPOT_SHEET_ID (which
                               is a Google Sheet, not the HubSpot API).

    GA4_CREDENTIALS_JSON   Not used by this script — present for parity with
                           other build scripts that reuse the same CI step env.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.hubspot_client import fetch_fibbler_companies, fetch_new_contacts_by_source
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "performance", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "performance", "index.html")

ENGAGEMENT_LEVELS = ["VERY_HIGH", "HIGH", "MEDIUM", "LOW", "VERY_LOW"]
HIGH_ENGAGEMENT   = {"VERY_HIGH", "HIGH"}
PIPELINE_STAGES_OPEN = {
    # ⚠️  Confirm these hs_pipeline_stage values against your HubSpot portal.
    # Typically these are numeric stage IDs or names like "appointmentscheduled".
    # Leave empty to treat any non-empty pipelineStage as "open deal".
}


def build_payload() -> dict:
    print("=" * 60)
    print("Building performance/index.html — HubSpot + Fibbler data")
    print("=" * 60)

    # ── 1. Fibbler company data ───────────────────────────────────────────────
    print("\n[1/2] Fetching Fibbler company engagement data…")
    companies = fetch_fibbler_companies()

    # Engagement level distribution
    engagement_summary = {level: 0 for level in ENGAGEMENT_LEVELS}
    for co in companies:
        lvl = (co.get("engagementLevel") or "").upper()
        if lvl in engagement_summary:
            engagement_summary[lvl] += 1

    # Pipeline overlap: HIGH or VERY_HIGH engagement + open deal
    # Assumption: hasOpenDeal is True when the `amount` field on the company
    # record is > 0.  If deal data lives only on Deal objects and is not synced
    # to the Company record, hasOpenDeal will always be False and pipelineOverlap
    # counts will be 0.  In that case a separate Deals API query is needed.
    overlap_companies = [
        co for co in companies
        if co["engagementLevel"].upper() in HIGH_ENGAGEMENT and co["hasOpenDeal"]
    ]
    overlap_companies.sort(key=lambda c: -c["dealValue"])

    pipeline_overlap = {
        "count":          len(overlap_companies),
        "totalDealValue": round(sum(c["dealValue"] for c in overlap_companies), 2),
        "topCompanies":   [
            {
                "name":             c["name"],
                "domain":           c["domain"],
                "industry":         c["industry"],
                "engagementLevel":  c["engagementLevel"],
                "dealValue":        c["dealValue"],
            }
            for c in overlap_companies[:10]
        ],
    }

    # Shape fibblerCompanies for the front end (drop internal fields not needed)
    fibbler_companies_out = [
        {
            "name":             co["name"],
            "domain":           co["domain"],
            "industry":         co["industry"],
            "employees":        co["employees"],
            "engagementLevel":  co["engagementLevel"],
            "impressions30":    co["impressions30"],
            "clicks30":         co["clicks30"],
            "engagements30":    co["engagements30"],
            "lifecyclestage":   co["lifecyclestage"],
            "hasOpenDeal":      co["hasOpenDeal"],
            "dealValue":        co["dealValue"],
        }
        for co in companies
    ]

    # ── 2. Contact acquisition by source ─────────────────────────────────────
    print("\n[2/2] Fetching new contacts by source (last 30 days)…")
    contacts_by_source = fetch_new_contacts_by_source(days=30)

    # ── 3. Assemble payload ───────────────────────────────────────────────────
    payload = {
        "fibblerCompanies":  fibbler_companies_out,
        "engagementSummary": engagement_summary,
        "pipelineOverlap":   pipeline_overlap,
        "contactsBySource":  contacts_by_source,
        "lastUpdated":       date.today().isoformat(),
    }

    total_with_data = len(companies)
    print(f"\n✅  Payload ready — {total_with_data} companies, "
          f"{pipeline_overlap['count']} pipeline overlaps, "
          f"{len(contacts_by_source)} contact sources")
    return payload


def main():
    try:
        data = build_payload()
    except EnvironmentError as exc:
        # Give a clear message if the token is missing rather than crashing CI
        print(f"\n❌  Configuration error: {exc}", file=sys.stderr)
        print("    Add HUBSPOT_ACCESS_TOKEN to GitHub repository secrets.", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌  Build failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        inject_data(
            template_path=TEMPLATE,
            data_dict={"PERF": data},
            output_path=OUTPUT,
        )
    except Exception as exc:
        print(f"\n❌  HTML injection failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
scripts/build_performance.py
Builds performance/index.html — HubSpot leads + Fibbler LinkedIn campaign data.

Data sources:
    HubSpot CRM API                   → new leads (two windows), lead journey, lead quality trend
    performance/fibbler_snapshot.json → Fibbler campaign performance (updated via Claude MCP)

Environment variables required:
    HUBSPOT_ACCESS_TOKEN    HubSpot Private App token
                            Scopes: crm.objects.contacts.read

No Fibbler credentials needed — campaign data is read from
performance/fibbler_snapshot.json, which is committed to the repo and
refreshed on demand via Claude Code + Fibbler MCP tools.
"""

import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.hubspot_client import (
    fetch_new_leads,
    fetch_lead_journey,
    fetch_notable_leads,
    fetch_lead_quality_trend,
)
from scripts.shared.html_utils import inject_data

REPO_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_PATH = os.path.join(REPO_ROOT, "performance", "fibbler_snapshot.json")
TEMPLATE      = os.path.join(REPO_ROOT, "performance", "index.html")
OUTPUT        = os.path.join(REPO_ROOT, "performance", "index.html")


def _load_fibbler_snapshot() -> dict:
    if not os.path.exists(SNAPSHOT_PATH):
        print("  ⚠️  fibbler_snapshot.json not found — campaign section will show no data.")
        return {}
    with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_payload() -> dict:
    today = date.today()

    print("=" * 60)
    print("Building performance/index.html")
    print("=" * 60)

    # ── Window date math ──────────────────────────────────────────────────────
    # Window 1 — this week (last 7 days) vs last week (7–14 days ago)
    w1_sel_start = today - timedelta(days=7)
    w1_sel_end   = today
    w1_cmp_start = today - timedelta(days=14)
    w1_cmp_end   = today - timedelta(days=7)

    # Window 2 — last week (7–14 days ago) vs two weeks ago (14–21 days ago)
    w2_sel_start = today - timedelta(days=14)
    w2_sel_end   = today - timedelta(days=7)
    w2_cmp_start = today - timedelta(days=21)
    w2_cmp_end   = today - timedelta(days=14)

    # ── 1. New Leads — window 1 ───────────────────────────────────────────────
    print("\n[1/4] New leads — this week vs last week…")
    leads_w1 = fetch_new_leads(w1_sel_start, w1_sel_end, w1_cmp_start, w1_cmp_end)

    # ── 2. New Leads — window 2 ───────────────────────────────────────────────
    print("\n[2/4] New leads — last week vs two weeks ago…")
    leads_w2 = fetch_new_leads(w2_sel_start, w2_sel_end, w2_cmp_start, w2_cmp_end)

    # ── 3. Lead Journey — window 1 (selected: this week) ─────────────────────
    print("\n[3/6] Lead journey — this week…")
    journey_w1 = fetch_lead_journey(w1_sel_start, w1_sel_end)

    # ── 4. Lead Journey — window 2 (selected: last week) ─────────────────────
    print("\n[4/6] Lead journey — last week…")
    journey_w2 = fetch_lead_journey(w2_sel_start, w2_sel_end)

    # ── 5. Lead Quality Trend — window 1 (8 weeks ending today) ──────────────
    print("\n[5/6] Lead quality score trend — window 1…")
    quality_w1 = fetch_lead_quality_trend(weeks=8, reference_date=w1_sel_end)

    # ── 6. Lead Quality Trend — window 2 (8 weeks ending last week) ──────────
    print("\n[6/8] Lead quality score trend — window 2…")
    quality_w2 = fetch_lead_quality_trend(weeks=8, reference_date=w2_sel_end)

    # ── 7. Notable Leads — window 1 ───────────────────────────────────────────
    print("\n[7/8] Notable leads — this week…")
    notable_w1 = fetch_notable_leads(w1_sel_start, w1_sel_end)

    # ── 8. Notable Leads — window 2 ───────────────────────────────────────────
    print("\n[8/8] Notable leads — last week…")
    notable_w2 = fetch_notable_leads(w2_sel_start, w2_sel_end)

    # ── Fibbler: campaign data from committed snapshot ─────────────────────────
    print("\nLoading Fibbler snapshot…")
    snap      = _load_fibbler_snapshot()
    campaigns = snap.get("campaigns") or []

    payload = {
        "windows": {
            "current_vs_last": {
                "label":           "This week vs. last week",
                "selectedLabel":   "This week",
                "comparisonLabel": "Last week",
                "leads":           leads_w1,
                "leadJourney":     journey_w1,
                "leadQuality":     quality_w1,
                "notableLeads":    notable_w1,
            },
            "last_vs_prev": {
                "label":           "Last week vs. two weeks ago",
                "selectedLabel":   "Last week",
                "comparisonLabel": "Two weeks ago",
                "leads":           leads_w2,
                "leadJourney":     journey_w2,
                "leadQuality":     quality_w2,
                "notableLeads":    notable_w2,
            },
        },
        "campaigns":   campaigns,
        "lastUpdated": today.isoformat(),
    }

    print(
        f"\n✅  Payload ready — "
        f"leads(w1)={leads_w1['selected']}, "
        f"leads(w2)={leads_w2['selected']}, "
        f"notable(w1)={len(notable_w1)}, "
        f"campaigns={len(campaigns)}"
    )
    return payload


def main():
    try:
        data = build_payload()
    except EnvironmentError as exc:
        print(f"\n❌  Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌  Build failed: {exc}", file=sys.stderr)
        raise

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

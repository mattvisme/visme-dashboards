#!/usr/bin/env python3
"""
scripts/build_performance.py
Builds performance/index.html — HubSpot leads + Fibbler LinkedIn attribution.

Data sources:
    HubSpot CRM API            → new leads, lead journey, lead quality trend
    performance/fibbler_snapshot.json  → Fibbler deal attribution + company
                                          engagement (updated via Claude MCP)

Environment variables required:
    HUBSPOT_ACCESS_TOKEN    HubSpot Private App token
                            Scopes: crm.objects.contacts.read

No Fibbler or Sheets credentials needed — Fibbler data is read from
performance/fibbler_snapshot.json, which is committed to the repo and
refreshed on demand via Claude Code + Fibbler MCP tools.
"""

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.hubspot_client import (
    fetch_new_leads,
    fetch_lead_journey,
    fetch_lead_quality_trend,
)
from scripts.shared.html_utils import inject_data

REPO_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_PATH = os.path.join(REPO_ROOT, "performance", "fibbler_snapshot.json")
TEMPLATE      = os.path.join(REPO_ROOT, "performance", "index.html")
OUTPUT        = os.path.join(REPO_ROOT, "performance", "index.html")

VERY_HIGH = "VERY_HIGH"


def _wow_pct(this_val: float, last_val: float) -> float | None:
    if last_val == 0:
        return None
    return round((this_val - last_val) / last_val * 100, 1)


def _load_fibbler_snapshot() -> dict:
    """Load performance/fibbler_snapshot.json."""
    if not os.path.exists(SNAPSHOT_PATH):
        print("  ⚠️  fibbler_snapshot.json not found — Fibbler sections will show no data.")
        return {"current": {}, "previous": None}
    with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_payload() -> dict:
    today = date.today()

    print("=" * 60)
    print("Building performance/index.html")
    print("=" * 60)

    # ── 1. HubSpot: new leads WoW ─────────────────────────────────────────────
    print("\n[1/3] New leads WoW…")
    leads = fetch_new_leads(days=7)

    # ── 2. HubSpot: lead journey ──────────────────────────────────────────────
    print("\n[2/3] Lead journey (hs_lead_status, scoped to paid+form leads, last 30 days)…")
    lead_journey = fetch_lead_journey(days=30)

    # ── 3. HubSpot: lead quality trend ────────────────────────────────────────
    print("\n[3/3] Lead quality score trend (8 weeks)…")
    lead_quality = fetch_lead_quality_trend(weeks=8)

    # ── Fibbler: read from committed snapshot ─────────────────────────────────
    print("\nLoading Fibbler snapshot…")
    snap = _load_fibbler_snapshot()
    cur  = snap.get("current") or {}
    prev = snap.get("previous")
    no_prior = prev is None

    # Pipeline section
    pipeline_this       = float(cur.get("pipelineValue",    0) or 0)
    pipeline_last       = float((prev or {}).get("pipelineValue",    0) or 0)
    pipeline_deals      = int(cur.get("pipelineDealCount",  0) or 0)
    pipeline_deals_last = int((prev or {}).get("pipelineDealCount",  0) or 0)

    pipeline = {
        "thisWeek":          pipeline_this,
        "lastWeek":          pipeline_last,
        "wowDelta":          round(pipeline_this - pipeline_last, 2),
        "wowPct":            _wow_pct(pipeline_this, pipeline_last),
        "dealCount":         pipeline_deals,
        "dealCountLastWeek": pipeline_deals_last,
    }

    # Closed Won section
    cw_this       = float(cur.get("closedWonValue",  0) or 0)
    cw_last       = float((prev or {}).get("closedWonValue",  0) or 0)
    cw_deals      = int(cur.get("closedWonCount",    0) or 0)
    cw_deals_last = int((prev or {}).get("closedWonCount",    0) or 0)

    closed_won = {
        "thisWeek":          cw_this,
        "lastWeek":          cw_last,
        "wowDelta":          round(cw_this - cw_last, 2),
        "wowPct":            _wow_pct(cw_this, cw_last),
        "dealCount":         cw_deals,
        "dealCountLastWeek": cw_deals_last,
    }

    # VERY_HIGH engagement section
    companies = cur.get("companies") or []
    very_high_companies = sorted(
        [c for c in companies if (c.get("engagementLevel") or "").upper() == VERY_HIGH],
        key=lambda c: -int(c.get("engagements", 0) or 0),
    )
    very_high_count = len(very_high_companies)
    vh_last = int((prev or {}).get("veryHighCount", 0) or 0)

    very_high_engagement = {
        "thisWeek": very_high_count,
        "lastWeek": vh_last,
        "wowDelta": very_high_count - vh_last,
        "wowPct":   _wow_pct(very_high_count, vh_last),
        "companies": [
            {
                "name":        c.get("name", ""),
                "industry":    c.get("industry", ""),
                "impressions": int(c.get("impressions", 0) or 0),
                "engagements": int(c.get("engagements", 0) or 0),
            }
            for c in very_high_companies[:10]
        ],
    }

    payload = {
        "leads":              leads,
        "leadJourney":        lead_journey,
        "leadQuality":        lead_quality,
        "pipeline":           pipeline,
        "closedWon":          closed_won,
        "veryHighEngagement": very_high_engagement,
        "noPriorSnapshot":    no_prior,
        "lastUpdated":        today.isoformat(),
        "snapshotNote": (
            "WoW comparisons are based on the previous Fibbler snapshot. "
            "Refresh via Claude Code + Fibbler MCP tools, then rebuild."
        ),
    }

    print(
        f"\n✅  Payload ready — "
        f"leads={leads['thisWeek']}, "
        f"pipeline=${pipeline_this:,.0f}, "
        f"veryHigh={very_high_count}"
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

#!/usr/bin/env python3
"""
scripts/check_gsc_anomaly.py
Weekly anomaly detection for Google Search Console performance, posted to Slack.

Reads the same `gsc_weekly` tab (via scripts/shared/sheets_client.py's
fetch_gsc_sheet_data) that scripts/build_gsc.py uses, including its existing
3-day processing-lag exclusion — so this check only ever looks at fully
settled weeks. Read-only / notify-only: does not touch gsc/index.html.

Scheduled separately from the daily traffic/signup checks because GSC data
itself only updates weekly.

Usage:
    python scripts/check_gsc_anomaly.py

Environment variables:
    GA4_CREDENTIALS_JSON   JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE   Path to service account JSON file (local dev)
    GSC_SHEET_ID           Google Sheet ID for GSC data
    SLACK_WEBHOOK_URL      Incoming webhook URL to post alerts to
"""

import os
import statistics
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.sheets_client import fetch_gsc_sheet_data
from scripts.shared.slack_client import post_to_slack, build_anomaly_message

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# ── TUNABLE THRESHOLDS ─────────────────────────────────────────────────────────
BASELINE_WEEKS        = 4      # trailing complete weeks to average, excluding the latest week
CLICKS_DROP_RATIO      = 0.30  # flag if weekly clicks drop more than 30% vs. baseline
POSITION_WORSEN_DELTA  = 3.0   # flag if avg position worsens (increases) by more than this


def _week_end_label(monday_str: str) -> str:
    d = date.fromisoformat(monday_str) + timedelta(days=6)
    return d.isoformat()


def check_gsc_anomaly(sheet_id: str) -> list[dict]:
    data = fetch_gsc_sheet_data(sheet_id=sheet_id)
    weeks = data.get("weeks", [])  # sorted oldest -> newest, Monday strings; unsettled weeks already excluded

    if len(weeks) < BASELINE_WEEKS + 1:
        print(f"  Not enough settled weeks yet ({len(weeks)} found, need {BASELINE_WEEKS + 1}) — skipping.")
        return []

    latest_week = weeks[-1]
    baseline_weeks = weeks[-(BASELINE_WEEKS + 1):-1]
    print(f"  Latest settled week: {latest_week} (ends {_week_end_label(latest_week)})")
    print(f"  Baseline weeks: {baseline_weeks}")

    w_clicks = data.get("wClicks", {})
    w_position = data.get("wPosition", {})

    latest_clicks = w_clicks.get(latest_week, 0)
    baseline_clicks_vals = [w_clicks.get(w, 0) for w in baseline_weeks]
    baseline_clicks_avg = statistics.mean(baseline_clicks_vals) if baseline_clicks_vals else 0.0

    latest_position = w_position.get(latest_week)
    baseline_position_vals = [w_position[w] for w in baseline_weeks if w_position.get(w) is not None]
    baseline_position_avg = statistics.mean(baseline_position_vals) if baseline_position_vals else None

    findings = []

    if baseline_clicks_avg > 0:
        pct_change = (latest_clicks - baseline_clicks_avg) / baseline_clicks_avg
        if pct_change <= -CLICKS_DROP_RATIO:
            findings.append({
                "summary": f"Weekly organic clicks dropped {abs(pct_change) * 100:.0f}% for week ending {_week_end_label(latest_week)}",
                "fields": [
                    ("Week ending", _week_end_label(latest_week)),
                    ("Clicks this week", f"{latest_clicks:,}"),
                    (f"{BASELINE_WEEKS}-wk baseline avg", f"{baseline_clicks_avg:,.0f}"),
                    ("% change", f"{pct_change * 100:+.1f}%"),
                    ("Threshold", f"> {CLICKS_DROP_RATIO * 100:.0f}% drop"),
                ],
            })
    else:
        print("  Skipping clicks-drop check — no positive baseline clicks.")

    if latest_position is not None and baseline_position_avg is not None:
        delta = latest_position - baseline_position_avg  # higher position number = worse ranking
        if delta >= POSITION_WORSEN_DELTA:
            findings.append({
                "summary": f"Weekly average position worsened by {delta:.1f} for week ending {_week_end_label(latest_week)}",
                "fields": [
                    ("Week ending", _week_end_label(latest_week)),
                    ("Avg position this week", f"{latest_position:.1f}"),
                    (f"{BASELINE_WEEKS}-wk baseline avg", f"{baseline_position_avg:.1f}"),
                    ("Position change", f"+{delta:.1f} (worse)"),
                    ("Threshold", f"> {POSITION_WORSEN_DELTA:.1f} positions worse"),
                ],
            })
    else:
        print("  Skipping position-worsen check — missing position data.")

    return findings


def main():
    print("=" * 60)
    print("Anomaly check: GSC weekly clicks/position drop")
    print("=" * 60)

    sheet_id = os.environ.get("GSC_SHEET_ID", "")
    if not sheet_id:
        print("ERROR: GSC_SHEET_ID environment variable is not set.")
        sys.exit(1)

    if not SLACK_WEBHOOK_URL:
        print("WARNING: SLACK_WEBHOOK_URL is not set — findings will be logged but not posted.")

    try:
        findings = check_gsc_anomaly(sheet_id)
    except Exception as exc:
        print(f"\nGSC anomaly check FAILED: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"{len(findings)} finding(s)")
    if findings:
        text, blocks = build_anomaly_message(
            "check_gsc_anomaly.py",
            "GSC Weekly Performance Anomaly",
            findings,
            severity="warning",
        )
        if SLACK_WEBHOOK_URL:
            post_to_slack(SLACK_WEBHOOK_URL, text, blocks)
        else:
            print(text)

    print("Done.")


if __name__ == "__main__":
    main()

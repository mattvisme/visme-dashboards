#!/usr/bin/env python3
"""
scripts/check_traffic_anomaly.py
Daily anomaly detection for website traffic (bot spikes) and PLG signups
(tracking breaks / fake signups), posted to Slack.

Mirrors the GA4 property + query patterns used by scripts/build_website.py
and scripts/build_plg_signups.py, but does NOT touch either dashboard's
index.html — this script is read-only / notify-only.

Checks 1 and 2 read from the same GA4 property and share one client session,
but each runs in its own try/except so a bug or empty result in one check
never prevents the other from running or alerting.

Usage:
    python scripts/check_traffic_anomaly.py

Environment variables:
    GA4_CREDENTIALS_JSON   JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE   Path to service account JSON file (local dev)
    GA4_PROPERTY_ID        GA4 property ID (default: 368188880)
    SLACK_WEBHOOK_URL      Incoming webhook URL to post alerts to

# ── DETECTION WINDOW ──────────────────────────────────────────────────────────
# "Last 48 hours" = the two most recently *complete* calendar days, with an
# extra DATA_LAG_BUFFER_DAYS-day buffer before "today" — not just yesterday.
# GA4's default channel grouping and event data can still be finalizing for a
# day or so after it ends (processing lag, plus the GA4 property's timezone
# vs. the UTC runner's calendar day can disagree by a day), so treating
# "yesterday" as complete can pull a partially-processed day and show
# spurious 0s. Buffering back one extra day means the freshest day this
# check ever looks at is 2 days old, and the older of the two is 3 days old.
# Each day is compared against the trailing 4-week average for that same day
# of week (e.g. a Tuesday is compared to the prior 4 Tuesdays), which controls
# for weekday seasonality (weekends vs. weekdays, etc.).
# ─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import time
import tempfile
import statistics
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest,
    FilterExpression, FilterExpressionList, Filter,
)
from google.oauth2 import service_account

from scripts.shared.slack_client import post_to_slack, build_anomaly_message

PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "368188880")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# ── TUNABLE THRESHOLDS ─────────────────────────────────────────────────────────
# All named here so they're easy to find and tune without hunting through logic.

BASELINE_WEEKS = 4          # trailing same-day-of-week weeks to average
DATA_LAG_BUFFER_DAYS = 1    # extra days of buffer before "yesterday", to avoid GA4
                            # processing lag / timezone drift showing up as 0s

# -- Check 1: website traffic bot-spike --
CHANNEL_SPIKE_MULTIPLIER      = 3.0    # flag if today > 3x the 4-week baseline
CHANNEL_SPIKE_MIN_ABS_SESSIONS = 20    # ignore ratio spikes on tiny channels (noise floor)
CHANNEL_NEW_SPIKE_ABS_SESSIONS = 50    # flag if baseline is ~0 and today has this many sessions
NOT_SET_SESSIONS_THRESHOLD    = 200    # Aug 4 incident fingerprint: (not set)/(not set) sessions/day
NOT_SET_ENGAGEMENT_RATE_MAX   = 0.05   # ...combined with engagement rate below this
TOP_N_BREAKDOWN               = 5      # top N countries/browsers shown per finding

# -- Check 2: PLG signup-drop --
SIGNUP_TOTAL_DROP_RATIO        = 0.5   # flag if today's total signups < 50% of baseline
SIGNUP_TOTAL_MIN_BASELINE      = 10    # ignore drop check on days with near-zero signup volume
SIGNUP_CHANNEL_ZERO_MIN_BASELINE = 5   # a channel's 4-week avg must be >= this to flag a zero-day
SIGNUP_SPIKE_MULTIPLIER        = 3.0   # secondary signal: channel signups spike 3x+
SIGNUP_SPIKE_MIN_ABS           = 10    # noise floor for the ratio-based signup spike check
SIGNUP_SPIKE_NEW_ABS           = 15    # flag if baseline is ~0 and today has this many signups


# ── AUTH ──────────────────────────────────────────────────────────────────────

def _get_credentials():
    """Load service account credentials — same pattern as build_website.py."""
    creds_json = os.environ.get("GA4_CREDENTIALS_JSON")
    if creds_json:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(creds_json)
        tmp.close()
        creds_file = tmp.name
    else:
        creds_file = os.environ.get(
            "GA4_CREDENTIALS_FILE",
            os.path.join(os.path.expanduser("~"), "Downloads",
                         "visme-marketing-491309-8316da126688.json"),
        )
    return service_account.Credentials.from_service_account_file(
        creds_file,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )


# ── DATE HELPERS ──────────────────────────────────────────────────────────────

def _target_days() -> list[date]:
    """
    The two most recently complete calendar days, oldest first — buffered
    DATA_LAG_BUFFER_DAYS days behind "today" so GA4 has had time to finalize
    them (see DETECTION WINDOW note above). With the default buffer of 1,
    this is 2 and 3 days before today, not yesterday and the day before.
    """
    today = date.today()
    latest = today - timedelta(days=1 + DATA_LAG_BUFFER_DAYS)
    return [latest - timedelta(days=1), latest]


def _baseline_days(target: date) -> list[date]:
    """Same weekday, one to BASELINE_WEEKS weeks before `target`."""
    return [target - timedelta(weeks=w) for w in range(1, BASELINE_WEEKS + 1)]


def _ga4_date_range_for(days: list[date]) -> tuple[str, str]:
    """Widest [start, end] window (YYYY-MM-DD) covering all targets + their baselines."""
    all_days = list(days)
    for d in days:
        all_days.extend(_baseline_days(d))
    return min(all_days).strftime("%Y-%m-%d"), max(all_days).strftime("%Y-%m-%d")


def _pct_change(today_value: float, baseline_avg: float) -> str:
    if baseline_avg <= 0:
        return "n/a (no baseline)"
    return f"{(today_value - baseline_avg) / baseline_avg * 100:+.0f}%"


# ── GA4 FILTER HELPERS ────────────────────────────────────────────────────────

def _exact_filter(field_name: str, value: str) -> FilterExpression:
    return FilterExpression(
        filter=Filter(
            field_name=field_name,
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.EXACT,
                value=value,
            ),
        )
    )


def _and_filter(*expressions: FilterExpression) -> FilterExpression:
    return FilterExpression(and_group=FilterExpressionList(expressions=list(expressions)))


def _event_filter(event_name: str) -> FilterExpression:
    return _exact_filter("eventName", event_name)


# ── GA4 RUNNER ────────────────────────────────────────────────────────────────

def _run(client, prop, start_date, end_date, dimensions, metrics, row_limit=50_000, dimension_filter=None):
    """Execute a GA4 RunReport with 4-attempt retry (15 / 30 / 60 s backoff)."""
    req_kwargs = dict(
        property=prop,
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        limit=row_limit,
    )
    if dimension_filter is not None:
        req_kwargs["dimension_filter"] = dimension_filter
    req = RunReportRequest(**req_kwargs)
    for attempt in range(4):
        try:
            resp = client.run_report(req, timeout=120)
            break
        except Exception as exc:
            if attempt == 3:
                raise
            wait = 15 * (2 ** attempt)
            print(f"  GA4 retry {attempt + 1}/4 in {wait}s: {exc}")
            time.sleep(wait)
    return [
        [dv.value for dv in row.dimension_values] + [mv.value for mv in row.metric_values]
        for row in resp.rows
    ]


def _int(v):
    try:
        return int(float(v))
    except Exception:
        return 0


def _float(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _spike(baseline_avg: float, today_value: float, multiplier: float, min_abs_ratio: float, min_abs_new: float) -> bool:
    """
    True if `today_value` looks like a spike vs. `baseline_avg`.
    Uses an absolute noise floor so tiny channels don't trip the ratio check,
    and falls back to an absolute threshold when there's effectively no baseline.
    """
    if baseline_avg > 0:
        return today_value >= min_abs_ratio and today_value > baseline_avg * multiplier
    return today_value >= min_abs_new


# ── BREAKDOWN QUERIES (top country/browser for an anomalous segment) ─────────

def _top_breakdown(client, prop, day_str: str, dimension_filter, dimension_name: str, top_n=TOP_N_BREAKDOWN) -> str:
    """Return 'Country A (123), Country B (45), ...' for the top N values of a dimension on one day."""
    try:
        rows = _run(client, prop, day_str, day_str, [dimension_name], ["sessions"],
                    row_limit=1000, dimension_filter=dimension_filter)
    except Exception as exc:
        return f"(breakdown unavailable: {exc})"
    rows = sorted(rows, key=lambda r: -_int(r[1]))[:top_n]
    if not rows:
        return "(no rows)"
    return ", ".join(f"{name} ({_int(sess):,})" for name, sess in rows)


# ── CHECK 1: WEBSITE TRAFFIC BOT-SPIKE ────────────────────────────────────────

def check_website_traffic_anomaly(client, prop) -> list[dict]:
    days = _target_days()
    start, end = _ga4_date_range_for(days)
    print(f"[check 1] website traffic anomaly — pulling {start} -> {end}")

    # Sessions by day x channel
    raw_ch = _run(client, prop, start, end,
                  ["date", "sessionDefaultChannelGrouping"], ["sessions"])
    sessions_by_day_channel: dict[str, dict[str, int]] = {}
    for date_str, ch, sess in raw_ch:
        sessions_by_day_channel.setdefault(date_str, {})[ch] = sessions_by_day_channel.get(date_str, {}).get(ch, 0) + _int(sess)

    # sessionSource x sessionMedium x day, for the (not set)/(not set) bot fingerprint
    raw_src = _run(client, prop, start, end,
                   ["date", "sessionSource", "sessionMedium"], ["sessions", "engagementRate"])
    not_set_by_day: dict[str, dict] = {}
    for date_str, src, med, sess, eng in raw_src:
        if src != "(not set)" or med != "(not set)":
            continue
        prev = not_set_by_day.get(date_str, {"sessions": 0, "engagementRate": 0.0})
        prev_sess = prev["sessions"]
        new_sess = _int(sess)
        total = prev_sess + new_sess
        avg_eng = (prev["engagementRate"] * prev_sess + _float(eng) * new_sess) / total if total else 0.0
        not_set_by_day[date_str] = {"sessions": total, "engagementRate": avg_eng}

    findings = []

    for day in days:
        day_str = _yyyymmdd(day)
        baseline_days = [_yyyymmdd(bd) for bd in _baseline_days(day)]
        today_channels = sessions_by_day_channel.get(day_str, {})

        # -- per-channel spike vs. trailing 4-week same-weekday average --
        for channel, today_sess in today_channels.items():
            baseline_vals = [sessions_by_day_channel.get(bd, {}).get(channel, 0) for bd in baseline_days]
            baseline_avg = statistics.mean(baseline_vals) if baseline_vals else 0.0
            if _spike(baseline_avg, today_sess, CHANNEL_SPIKE_MULTIPLIER,
                      CHANNEL_SPIKE_MIN_ABS_SESSIONS, CHANNEL_NEW_SPIKE_ABS_SESSIONS):
                day_iso = day.isoformat()
                # Breakdown queries scope to this single day via the date range, so the
                # dimension filter only needs to match the channel itself.
                dim_filter = _exact_filter("sessionDefaultChannelGrouping", channel)
                findings.append({
                    "summary": f"Channel spike: *{channel}* on {day_iso}",
                    "fields": [
                        ("Date", day_iso),
                        ("Channel", channel),
                        ("Sessions today", f"{today_sess:,}"),
                        (f"{BASELINE_WEEKS}-wk baseline avg", f"{baseline_avg:,.1f}"),
                        ("% change", _pct_change(today_sess, baseline_avg)),
                        ("Top countries", _top_breakdown(client, prop, day_iso, dim_filter, "country")),
                        ("Top browsers", _top_breakdown(client, prop, day_iso, dim_filter, "browser")),
                    ],
                })

        # -- (not set)/(not set) bot fingerprint (Aug 4 incident pattern) --
        ns = not_set_by_day.get(day_str, {"sessions": 0, "engagementRate": 1.0})
        if ns["sessions"] > NOT_SET_SESSIONS_THRESHOLD and ns["engagementRate"] < NOT_SET_ENGAGEMENT_RATE_MAX:
            day_iso = day.isoformat()
            ns_filter = _and_filter(
                _exact_filter("sessionSource", "(not set)"),
                _exact_filter("sessionMedium", "(not set)"),
            )
            findings.append({
                "summary": f"Bot-traffic fingerprint: source=(not set) & medium=(not set) on {day_iso}",
                "fields": [
                    ("Date", day_iso),
                    ("Sessions today", f"{ns['sessions']:,}"),
                    ("Engagement rate", f"{ns['engagementRate'] * 100:.1f}%"),
                    ("Threshold", f">{NOT_SET_SESSIONS_THRESHOLD} sessions & <{NOT_SET_ENGAGEMENT_RATE_MAX * 100:.0f}% engagement"),
                    ("Top countries", _top_breakdown(client, prop, day_iso, ns_filter, "country")),
                    ("Top browsers", _top_breakdown(client, prop, day_iso, ns_filter, "browser")),
                ],
            })

    return findings


# ── CHECK 2: PLG SIGNUP-DROP ──────────────────────────────────────────────────

def check_plg_signup_anomaly(client, prop) -> list[dict]:
    days = _target_days()
    start, end = _ga4_date_range_for(days)
    print(f"[check 2] PLG signup anomaly — pulling {start} -> {end}")

    raw_signups = _run(client, prop, start, end,
                        ["date", "sessionDefaultChannelGrouping"], ["eventCount"],
                        dimension_filter=_event_filter("register"))
    signups_by_day_channel: dict[str, dict[str, int]] = {}
    for date_str, ch, cnt in raw_signups:
        signups_by_day_channel.setdefault(date_str, {})[ch] = signups_by_day_channel.get(date_str, {}).get(ch, 0) + _int(cnt)

    raw_sessions = _run(client, prop, start, end,
                        ["date", "sessionDefaultChannelGrouping"], ["sessions"])
    sessions_by_day_channel: dict[str, dict[str, int]] = {}
    for date_str, ch, sess in raw_sessions:
        sessions_by_day_channel.setdefault(date_str, {})[ch] = sessions_by_day_channel.get(date_str, {}).get(ch, 0) + _int(sess)

    findings = []

    for day in days:
        day_str = _yyyymmdd(day)
        day_iso = day.isoformat()
        baseline_days = [_yyyymmdd(bd) for bd in _baseline_days(day)]
        today_channels = signups_by_day_channel.get(day_str, {})

        # -- total daily signups drop vs. trailing 4-week same-weekday average --
        total_today = sum(today_channels.values())
        baseline_totals = [sum(signups_by_day_channel.get(bd, {}).values()) for bd in baseline_days]
        baseline_total_avg = statistics.mean(baseline_totals) if baseline_totals else 0.0
        if baseline_total_avg >= SIGNUP_TOTAL_MIN_BASELINE and total_today < baseline_total_avg * SIGNUP_TOTAL_DROP_RATIO:
            findings.append({
                "summary": f"Total signups dropped on {day_iso} (possible tracking break or broken signup form)",
                "fields": [
                    ("Date", day_iso),
                    ("Signups today", f"{total_today:,}"),
                    (f"{BASELINE_WEEKS}-wk baseline avg", f"{baseline_total_avg:,.1f}"),
                    ("% change", _pct_change(total_today, baseline_total_avg)),
                    ("Threshold", f"< {SIGNUP_TOTAL_DROP_RATIO * 100:.0f}% of baseline"),
                ],
            })

        # -- per-channel zero-day drop + secondary spike/bot-signup signal --
        all_channels = set(today_channels) | {ch for bd in baseline_days for ch in signups_by_day_channel.get(bd, {})}
        for channel in all_channels:
            today_signups = today_channels.get(channel, 0)
            baseline_vals = [signups_by_day_channel.get(bd, {}).get(channel, 0) for bd in baseline_days]
            baseline_avg = statistics.mean(baseline_vals) if baseline_vals else 0.0

            if baseline_avg >= SIGNUP_CHANNEL_ZERO_MIN_BASELINE and today_signups == 0:
                findings.append({
                    "summary": f"Signups dropped to zero: *{channel}* on {day_iso}",
                    "fields": [
                        ("Date", day_iso),
                        ("Channel", channel),
                        ("Signups today", "0"),
                        (f"{BASELINE_WEEKS}-wk baseline avg", f"{baseline_avg:,.1f}"),
                    ],
                })
                continue  # zero-day and spike are mutually exclusive for the same channel/day

            if _spike(baseline_avg, today_signups, SIGNUP_SPIKE_MULTIPLIER,
                      SIGNUP_SPIKE_MIN_ABS, SIGNUP_SPIKE_NEW_ABS):
                # secondary/lower-severity: only interesting if sessions did NOT spike to match
                today_sess = sessions_by_day_channel.get(day_str, {}).get(channel, 0)
                sess_baseline_vals = [sessions_by_day_channel.get(bd, {}).get(channel, 0) for bd in baseline_days]
                sess_baseline_avg = statistics.mean(sess_baseline_vals) if sess_baseline_vals else 0.0
                session_also_spiked = _spike(sess_baseline_avg, today_sess, CHANNEL_SPIKE_MULTIPLIER,
                                              CHANNEL_SPIKE_MIN_ABS_SESSIONS, CHANNEL_NEW_SPIKE_ABS_SESSIONS)
                if not session_also_spiked:
                    findings.append({
                        "summary": f"⚠️ Secondary signal — signups spiked without a matching session spike: *{channel}* on {day_iso} (possible fake/bot signups)",
                        "fields": [
                            ("Date", day_iso),
                            ("Channel", channel),
                            ("Signups today", f"{today_signups:,}"),
                            (f"Signups {BASELINE_WEEKS}-wk avg", f"{baseline_avg:,.1f}"),
                            ("Sessions today", f"{today_sess:,}"),
                            (f"Sessions {BASELINE_WEEKS}-wk avg", f"{sess_baseline_avg:,.1f}"),
                        ],
                    })

    return findings


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Anomaly check: website traffic bot-spike + PLG signup-drop")
    print("=" * 60)

    if not SLACK_WEBHOOK_URL:
        print("WARNING: SLACK_WEBHOOK_URL is not set — findings will be logged but not posted.")

    creds = _get_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)
    prop = f"properties/{PROPERTY_ID}"

    exit_code = 0

    try:
        findings1 = check_website_traffic_anomaly(client, prop)
        print(f"[check 1] {len(findings1)} finding(s)")
        if findings1:
            text, blocks = build_anomaly_message(
                "check_traffic_anomaly.py (website)",
                "Website Traffic Anomaly — Possible Bot Spike",
                findings1,
                severity="critical",
            )
            if SLACK_WEBHOOK_URL:
                post_to_slack(SLACK_WEBHOOK_URL, text, blocks)
            else:
                print(text)
    except Exception as exc:
        print(f"[check 1] FAILED (does not block check 2): {exc}", file=sys.stderr)
        exit_code = 1

    try:
        findings2 = check_plg_signup_anomaly(client, prop)
        print(f"[check 2] {len(findings2)} finding(s)")
        if findings2:
            text, blocks = build_anomaly_message(
                "check_traffic_anomaly.py (plg signups)",
                "PLG Signup Anomaly",
                findings2,
                severity="warning",
            )
            if SLACK_WEBHOOK_URL:
                post_to_slack(SLACK_WEBHOOK_URL, text, blocks)
            else:
                print(text)
    except Exception as exc:
        print(f"[check 2] FAILED: {exc}", file=sys.stderr)
        exit_code = 1

    print("Done." if exit_code == 0 else "Done with errors — see above.")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

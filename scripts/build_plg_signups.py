#!/usr/bin/env python3
"""
scripts/build_plg_signups.py
Fetches GA4 free signup data and injects it into plg-signups/index.html.

Usage:
    python scripts/build_plg_signups.py

Environment variables:
    GA4_CREDENTIALS_JSON   JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE   Path to service account JSON file (local dev)
    GA4_PROPERTY_ID        GA4 property ID (default: 368188880)

# ── DATA MODEL ────────────────────────────────────────────────────────────────
#
# Three GA4 queries against visme.co (property 368188880):
#
# Query A — Signup counts by channel × week (13-week rolling window)
#   dimensions: date, sessionDefaultChannelGrouping
#   metric:     eventCount
#   filter:     eventName = "register"
#
# Query B — Total sessions by channel × week (same date range, no filter)
#   dimensions: date, sessionDefaultChannelGrouping
#   metric:     sessions
#   (used to compute true signup rate = signups / total sessions per channel)
#
# Query C — Signups by channel × country (same 13-week window)
#   dimensions: sessionDefaultChannelGrouping, country
#   metric:     eventCount, sessions
#   filter:     eventName = "register"
#
# Query D — Top pages by signups, last 4 weeks
#   dimensions: landingPagePlusQueryString
#   metrics:    sessions, eventCount
#   filter:     eventName = "register"
#
# ── WEEK BOUNDARY LOGIC ───────────────────────────────────────────────────────
# Same logic as build_website.py — Monday-to-Sunday spans, only complete weeks.
# See build_website.py module docstring for full explanation.
# ─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import time
import tempfile
import json
from datetime import date, datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest,
    FilterExpression, Filter,
)
from google.oauth2 import service_account

from scripts.shared.html_utils import inject_data

REPO_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE    = os.path.join(REPO_ROOT, "plg-signups", "index.html")
OUTPUT      = os.path.join(REPO_ROOT, "plg-signups", "index.html")
PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "368188880")
WEEKS       = 13


# ── AUTH ──────────────────────────────────────────────────────────────────────

def _get_credentials():
    """Load service account credentials from env var or local file."""
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

def _week_monday(date_str: str) -> str:
    """Return YYYY-MM-DD of the Monday for a GA4 YYYYMMDD date string."""
    d = datetime.strptime(date_str, "%Y%m%d").date()
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def _fmt_label(monday_str: str) -> str:
    """Format the Sunday end-date of a week as 'MMM D' label (e.g. 'Jun 15')."""
    d = datetime.strptime(monday_str, "%Y-%m-%d").date() + timedelta(days=6)
    if sys.platform == "win32":
        return d.strftime(f"%b {d.day}")
    return d.strftime("%b %-d")


def _compute_date_range():
    """
    Return (window_start_str, last_sunday_str, this_monday_str, as_of_date_str)
    for the trailing 13 complete weeks.
    """
    today        = date.today()
    this_monday  = today - timedelta(days=today.weekday())
    last_sunday  = this_monday - timedelta(days=1)
    window_start = this_monday - timedelta(weeks=WEEKS)

    as_of: date = last_sunday
    as_of_str = (
        as_of.strftime(f"%B {as_of.day}, %Y")
        if sys.platform == "win32"
        else as_of.strftime("%B %-d, %Y")
    )

    return (
        window_start.strftime("%Y-%m-%d"),
        last_sunday.strftime("%Y-%m-%d"),
        this_monday.strftime("%Y-%m-%d"),
        as_of_str,
    )


def _four_weeks_ago(this_monday_str: str) -> str:
    """Return YYYY-MM-DD of the Monday 4 weeks before this_monday."""
    d = datetime.strptime(this_monday_str, "%Y-%m-%d").date()
    return (d - timedelta(weeks=4)).strftime("%Y-%m-%d")


# ── GA4 RUNNER ────────────────────────────────────────────────────────────────

def _event_filter(event_name: str) -> FilterExpression:
    """Build a GA4 FilterExpression matching eventName exactly."""
    return FilterExpression(
        filter=Filter(
            field_name="eventName",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.EXACT,
                value=event_name,
            ),
        )
    )


def _run(client, prop, start_date, end_date, dimensions, metrics,
         row_limit=50_000, dimension_filter=None):
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
        return round(float(v), 4)
    except Exception:
        return 0.0


# ── MAIN FETCH ────────────────────────────────────────────────────────────────

def fetch_signup_data() -> dict:
    print("=" * 60)
    print("Building plg-signups/index.html — GA4 free signup decomposition")
    print("=" * 60)

    start_date, end_date, this_monday_str, as_of_date = _compute_date_range()
    pages_start = _four_weeks_ago(this_monday_str)
    pages_end   = end_date
    print(f"  13-week range: {start_date} -> {end_date}")
    print(f"  Top pages range: {pages_start} -> {pages_end}")

    creds  = _get_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)
    prop   = f"properties/{PROPERTY_ID}"
    reg_filter = _event_filter("register")

    # ── A. Signup eventCount by channel x week ───────────────────────────────
    print("Pulling register eventCount by channel x date ...")
    signups_weekly: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # {week_monday -> {channel -> signup_count}}
    raw_a = _run(client, prop, start_date, end_date,
                 ["date", "sessionDefaultChannelGrouping"],
                 ["eventCount"],
                 dimension_filter=reg_filter)
    for date_str, ch, cnt in raw_a:
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        signups_weekly[w][ch] += _int(cnt)

    # ── B. Total sessions by channel x week (for signup rate denominator) ────
    print("Pulling total sessions by channel x date ...")
    sessions_weekly: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    raw_b = _run(client, prop, start_date, end_date,
                 ["date", "sessionDefaultChannelGrouping"],
                 ["sessions"])
    for date_str, ch, sess in raw_b:
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        sessions_weekly[w][ch] += _int(sess)

    # ── C. Signup count + sessions by channel x country (all 13 weeks) ───────
    print("Pulling register eventCount by channel x country ...")
    country_signups: dict[str, list[dict]] = defaultdict(list)
    # {channel -> [{country, sessions, signups, rate}]}
    country_ch_agg: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"signups": 0, "sessions": 0}))
    raw_c = _run(client, prop, start_date, end_date,
                 ["sessionDefaultChannelGrouping", "country"],
                 ["eventCount", "sessions"],
                 dimension_filter=reg_filter)
    for ch, country, cnt, sess in raw_c:
        country_ch_agg[ch][country]["signups"]  += _int(cnt)
        country_ch_agg[ch][country]["sessions"] += _int(sess)

    for ch, countries in country_ch_agg.items():
        rows = []
        for country, vals in countries.items():
            if country in ("(not set)", ""):
                continue
            signups  = vals["signups"]
            sessions = vals["sessions"]
            rate = round(signups / sessions, 4) if sessions > 0 else 0.0
            rows.append({"country": country, "sessions": sessions, "signups": signups, "rate": rate})
        rows.sort(key=lambda r: -r["signups"])
        country_signups[ch] = rows[:10]  # top 10 countries per channel

    # ── D. Top landing pages by signup count, last 4 weeks ───────────────────
    print("Pulling top pages by register eventCount (last 4 weeks) ...")
    raw_d = _run(client, prop, pages_start, pages_end,
                 ["landingPagePlusQueryString"],
                 ["sessions", "eventCount"],
                 row_limit=100,
                 dimension_filter=reg_filter)
    top_pages = []
    for page, sess, cnt in raw_d:
        if page in ("(not set)", ""):
            continue
        signups  = _int(cnt)
        sessions = _int(sess)
        if signups == 0:
            continue
        top_pages.append({"page": page, "sessions": sessions, "signups": signups})
    top_pages.sort(key=lambda r: -r["signups"])
    top_pages = top_pages[:20]

    # ── Assemble sorted week list ─────────────────────────────────────────────
    all_mondays = sorted(
        w for w in set(signups_weekly.keys()) | set(sessions_weekly.keys())
        if w < this_monday_str
    )
    all_weeks = all_mondays[-WEEKS:]

    # Drop leading weeks that have zero total signups across all channels.
    # This keeps the chart clean when the register event didn't fire historically.
    while all_weeks:
        first_total = sum(signups_weekly[all_weeks[0]].get(ch, 0) for ch in signups_weekly[all_weeks[0]])
        if first_total == 0:
            all_weeks = all_weeks[1:]
        else:
            break

    labels = [_fmt_label(w) for w in all_weeks]

    # ── Build signupsByChannel ────────────────────────────────────────────────
    all_channels: set[str] = set()
    for w in all_weeks:
        all_channels.update(signups_weekly[w].keys())
    all_channels_sorted = sorted(
        all_channels,
        key=lambda c: -sum(signups_weekly[w].get(c, 0) for w in all_weeks),
    )

    signups_by_channel: dict[str, list] = {
        ch: [signups_weekly[w].get(ch, 0) for w in all_weeks]
        for ch in all_channels_sorted
    }

    total_signups_weekly = [
        sum(signups_weekly[w].get(ch, 0) for ch in all_channels)
        for w in all_weeks
    ]

    # ── Build channelSnapshot (latest week vs prior week) ────────────────────
    latest_w = all_weeks[-1] if all_weeks else None
    prior_w  = all_weeks[-2] if len(all_weeks) >= 2 else None
    channel_snapshot = []
    for ch in all_channels_sorted:
        this_signups = signups_weekly.get(latest_w, {}).get(ch, 0) if latest_w else 0
        prev_signups = signups_weekly.get(prior_w, {}).get(ch, 0) if prior_w else 0
        this_sessions = sessions_weekly.get(latest_w, {}).get(ch, 0) if latest_w else 0
        if this_signups == 0 and prev_signups == 0:
            continue
        rate = round(this_signups / this_sessions, 4) if this_sessions > 0 else 0.0
        channel_snapshot.append({
            "channel":     ch,
            "sessions":    this_sessions,
            "signups":     this_signups,
            "prevSignups": prev_signups,
            "rate":        rate,
        })
    channel_snapshot.sort(key=lambda r: -r["signups"])

    payload = {
        "dataAsOfDate":     as_of_date,
        "weeks":            all_weeks,
        "weekLabels":       labels,
        "channels":         all_channels_sorted,
        "signupsByChannel": signups_by_channel,
        "totalSignupsWeekly": total_signups_weekly,
        "channelSnapshot":  channel_snapshot,
        "countryByChannel": dict(country_signups),
        "topPages":         top_pages,
    }

    total_this_week = sum(r["signups"] for r in channel_snapshot)
    print(f"  Done — {len(all_weeks)} weeks, {len(all_channels_sorted)} channels, "
          f"{len(top_pages)} top pages, {total_this_week:,} signups this week")
    return payload


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    try:
        data = fetch_signup_data()
    except Exception as exc:
        print(f"\nGA4 fetch failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        inject_data(
            template_path=TEMPLATE,
            data_dict={"PLG": data},
            output_path=OUTPUT,
        )
    except Exception as exc:
        print(f"\nHTML injection failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()

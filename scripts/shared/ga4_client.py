"""
scripts/shared/ga4_client.py
Shared GA4 Data API helper for the visme-dashboards build system.
Extracted from build_dashboard.py in mattvisme/visme-dashboard.
"""

import json
import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from collections import defaultdict

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest,
    FilterExpression, Filter
)
from google.oauth2 import service_account

InListFilter = Filter.InListFilter

WEEKS_HISTORY = 156   # 3 years: 104 current + 52 prior-year buffer
TARGET_EVENTS = ["create_an_account", "visit_payment_page", "purchase"]


def _get_credentials(credentials_file=None):
    """Load credentials from JSON env var string or file path."""
    creds_json = os.environ.get("GA4_CREDENTIALS_JSON")
    if creds_json:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(creds_json)
        tmp.close()
        credentials_file = tmp.name

    if not credentials_file:
        credentials_file = os.environ.get(
            "GA4_CREDENTIALS_FILE",
            os.path.join(os.path.expanduser("~"), "Downloads",
                         "visme-marketing-491309-47059dacd5b9.json")
        )

    return service_account.Credentials.from_service_account_file(
        credentials_file,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )


def _get_monday_str(date_str: str) -> str:
    """Return the Monday of the week for a YYYYMMDD date string (GA4 date dimension format)."""
    d = datetime.strptime(date_str, "%Y%m%d").date()
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def _fmt_label(d: date) -> str:
    if sys.platform == "win32":
        return d.strftime(f"%b {d.day} '{d.strftime('%y')}")
    return d.strftime("%b %-d '%y")


def fetch_ga4_data(property_id=None, credentials_file=None) -> dict:
    """
    Fetch ~3 years of weekly GA4 data.

    Returns a dict matching the GA4 data structure expected by the dashboard
    HTML templates:
      {
        asOfDate, weeks, weekLabels, sessions, newUsers, nvr,
        channels, topChannels, geo, landingPages, events
      }

    Args:
        property_id: GA4 property ID string (defaults to env GA4_PROPERTY_ID)
        credentials_file: Path to service account JSON (defaults to env/default path)
    """
    if property_id is None:
        property_id = os.environ.get("GA4_PROPERTY_ID", "368188880")

    creds = _get_credentials(credentials_file)
    client = BetaAnalyticsDataClient(credentials=creds)
    prop = f"properties/{property_id}"

    today        = date.today()
    this_monday  = today - timedelta(days=today.weekday())   # Mon of current week
    last_sunday  = this_monday - timedelta(days=1)           # Sun of last complete week
    start_dt     = this_monday - timedelta(weeks=WEEKS_HISTORY)

    end_date         = last_sunday.strftime("%Y-%m-%d")
    start_date       = start_dt.strftime("%Y-%m-%d")
    this_monday_str  = this_monday.strftime("%Y-%m-%d")
    as_of_date       = last_sunday.strftime("%B %-d, %Y") if sys.platform != "win32" \
                       else last_sunday.strftime(f"%B {last_sunday.day}, %Y")

    print(f"📅  GA4 date range: {start_date} → {end_date}")

    def run(dimensions, metrics, row_limit=250_000, dim_filter=None):
        req = RunReportRequest(
            property=prop,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            limit=row_limit,
        )
        if dim_filter:
            req.dimension_filter = dim_filter
        for attempt in range(4):
            try:
                resp = client.run_report(req, timeout=120)
                break
            except Exception as e:
                if attempt == 3:
                    raise
                wait = 15 * (2 ** attempt)   # 15s, 30s, 60s
                print(f"  GA4 API error (attempt {attempt + 1}/4), retrying in {wait}s: {e}")
                time.sleep(wait)
        return [[d.value for d in r.dimension_values] + [m.value for m in r.metric_values]
                for r in resp.rows]

    def int_(v):
        try:
            return int(float(v))
        except Exception:
            return 0

    # 1. Sessions + New Users by week
    print("⏳  Pulling sessions + new users …")
    weekly_sessions, weekly_new_users = defaultdict(int), defaultdict(int)
    for date_str, sess, nu in run(["date"], ["sessions", "newUsers"]):
        w = _get_monday_str(date_str)
        weekly_sessions[w] += int_(sess)
        weekly_new_users[w] += int_(nu)

    # 2. New vs Returning by week
    print("⏳  Pulling new vs returning …")
    weekly_nvr = defaultdict(lambda: {"new": 0, "returning": 0})
    for date_str, nvr, sess in run(["date", "newVsReturning"], ["sessions"]):
        w   = _get_monday_str(date_str)
        key = "new" if nvr.lower() == "new" else "returning"
        weekly_nvr[w][key] += int_(sess)

    # 3. Channel by week
    print("⏳  Pulling channel sessions …")
    weekly_channels = defaultdict(lambda: defaultdict(int))
    all_channels = set()
    for date_str, ch, sess in run(["date", "sessionDefaultChannelGroup"], ["sessions"]):
        w = _get_monday_str(date_str)
        weekly_channels[w][ch] += int_(sess)
        all_channels.add(ch)

    channel_totals = defaultdict(int)
    for w_data in weekly_channels.values():
        for ch, v in w_data.items():
            channel_totals[ch] += v
    top_channels = [c for c, _ in sorted(channel_totals.items(), key=lambda x: -x[1])[:15]]

    # 4. US vs Non-US by week
    print("⏳  Pulling geo sessions …")
    weekly_geo = defaultdict(lambda: {"us": 0, "nonUs": 0})
    for date_str, country, sess in run(["date", "country"], ["sessions"],
                                       row_limit=500_000):
        w = _get_monday_str(date_str)
        if country == "United States":
            weekly_geo[w]["us"] += int_(sess)
        else:
            weekly_geo[w]["nonUs"] += int_(sess)

    # 5. Top Landing Pages (aggregate over full date range — no weekly grouping needed)
    print("⏳  Pulling landing pages …")
    landing_pages_raw = []
    for row in run(["landingPagePlusQueryString"], ["sessions", "newUsers", "bounceRate"],
                   row_limit=500):
        page, sess, nu, br = row
        landing_pages_raw.append({
            "page": page[:80],
            "sessions": int_(sess),
            "newUsers": int_(nu),
            "bounceRate": round(float(br) * 100, 1)
        })
    landing_pages_raw.sort(key=lambda x: -x["sessions"])
    top_landing_pages = landing_pages_raw[:10]

    # 6. Conversion Events by week
    print("⏳  Pulling conversion events …")
    event_filter = FilterExpression(
        filter=Filter(
            field_name="eventName",
            in_list_filter=InListFilter(values=TARGET_EVENTS)
        )
    )
    weekly_events = defaultdict(lambda: {e: 0 for e in TARGET_EVENTS})
    for date_str, evt, cnt in run(["date", "eventName"], ["eventCount"],
                                  dim_filter=event_filter):
        if evt in TARGET_EVENTS:
            w = _get_monday_str(date_str)
            weekly_events[w][evt] += int_(cnt)

    # Assemble sorted week list — complete Mon–Sun weeks only (week Monday < this Monday)
    all_weeks = sorted(set(
        list(weekly_sessions.keys()) + list(weekly_nvr.keys()) +
        list(weekly_channels.keys()) + list(weekly_geo.keys()) +
        list(weekly_events.keys())
    ))
    all_weeks = [w for w in all_weeks if w < this_monday_str]

    week_labels = {}
    for w in all_weeks:
        sunday = datetime.strptime(w, "%Y-%m-%d").date() + timedelta(days=6)
        week_labels[w] = _fmt_label(sunday)

    payload = {
        "asOfDate":    as_of_date,
        "weeks":       all_weeks,
        "weekLabels":  [week_labels.get(w, w) for w in all_weeks],
        "sessions":    {w: int(weekly_sessions.get(w, 0))  for w in all_weeks},
        "newUsers":    {w: int(weekly_new_users.get(w, 0)) for w in all_weeks},
        "nvr":         {w: dict(weekly_nvr.get(w, {"new": 0, "returning": 0})) for w in all_weeks},
        "channels":    {w: {ch: weekly_channels[w].get(ch, 0) for ch in top_channels} for w in all_weeks},
        "topChannels": top_channels,
        "geo":         {w: dict(weekly_geo.get(w, {"us": 0, "nonUs": 0})) for w in all_weeks},
        "landingPages": top_landing_pages,
        "events":      {w: dict(weekly_events.get(w, {e: 0 for e in TARGET_EVENTS})) for w in all_weeks},
    }

    print(f"✅  GA4 collected — {len(all_weeks)} weeks, {len(top_channels)} channels")
    return payload

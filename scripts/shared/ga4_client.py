"""
scripts/shared/ga4_client.py
Shared GA4 Data API helper for the visme-dashboards build system.
Extracted from build_dashboard.py in mattvisme/visme-dashboard.
"""

import json
import os
import sys
import tempfile
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


def _yw_to_monday(yw: str) -> date:
    """Convert GA4 yearWeek (e.g. '202403') to the Monday of that ISO week."""
    year, wk = int(yw[:4]), int(yw[4:])
    return datetime.strptime(f"{year}-W{wk:02d}-1", "%G-W%V-%u").date()


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

    today = date.today()
    last_sunday = today - timedelta(days=(today.weekday() + 1) % 7 or 7)
    start_dt = last_sunday - timedelta(weeks=WEEKS_HISTORY - 1)

    end_date = last_sunday.strftime("%Y-%m-%d")
    start_date = start_dt.strftime("%Y-%m-%d")
    as_of_date = last_sunday.strftime("%B %-d, %Y") if sys.platform != "win32" \
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
        resp = client.run_report(req)
        return [[d.value for d in r.dimension_values] + [m.value for m in r.metric_values]
                for r in resp.rows]

    def int_(v):
        try:
            return int(float(v))
        except Exception:
            return 0

    # 1. Sessions + New Users by week
    print("⏳  Pulling sessions + new users …")
    weekly_sessions, weekly_new_users = {}, {}
    for yw, sess, nu in run(["yearWeek"], ["sessions", "newUsers"]):
        weekly_sessions[yw] = int_(sess)
        weekly_new_users[yw] = int_(nu)

    # 2. New vs Returning by week
    print("⏳  Pulling new vs returning …")
    weekly_nvr = defaultdict(lambda: {"new": 0, "returning": 0})
    for yw, nvr, sess in run(["yearWeek", "newVsReturning"], ["sessions"]):
        key = "new" if nvr.lower() == "new" else "returning"
        weekly_nvr[yw][key] += int_(sess)

    # 3. Channel by week
    print("⏳  Pulling channel sessions …")
    weekly_channels = defaultdict(lambda: defaultdict(int))
    all_channels = set()
    for yw, ch, sess in run(["yearWeek", "sessionDefaultChannelGroup"], ["sessions"]):
        weekly_channels[yw][ch] += int_(sess)
        all_channels.add(ch)

    channel_totals = defaultdict(int)
    for yw_data in weekly_channels.values():
        for ch, v in yw_data.items():
            channel_totals[ch] += v
    top_channels = [c for c, _ in sorted(channel_totals.items(), key=lambda x: -x[1])[:15]]

    # 4. US vs Non-US by week
    print("⏳  Pulling geo sessions …")
    weekly_geo = defaultdict(lambda: {"us": 0, "nonUs": 0})
    for yw, country, sess in run(["yearWeek", "country"], ["sessions"]):
        if country == "United States":
            weekly_geo[yw]["us"] += int_(sess)
        else:
            weekly_geo[yw]["nonUs"] += int_(sess)

    # 5. Top Landing Pages (aggregate)
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
    for yw, evt, cnt in run(["yearWeek", "eventName"], ["eventCount"],
                            dim_filter=event_filter):
        if evt in TARGET_EVENTS:
            weekly_events[yw][evt] += int_(cnt)

    # Assemble sorted week list
    all_weeks = sorted(set(
        list(weekly_sessions.keys()) + list(weekly_nvr.keys()) +
        list(weekly_channels.keys()) + list(weekly_geo.keys()) +
        list(weekly_events.keys())
    ))

    week_labels = {}
    for yw in all_weeks:
        try:
            week_labels[yw] = _fmt_label(_yw_to_monday(yw))
        except Exception:
            week_labels[yw] = yw

    payload = {
        "asOfDate":    as_of_date,
        "weeks":       all_weeks,
        "weekLabels":  [week_labels.get(w, w) for w in all_weeks],
        "sessions":    {w: weekly_sessions.get(w, 0)  for w in all_weeks},
        "newUsers":    {w: weekly_new_users.get(w, 0) for w in all_weeks},
        "nvr":         {w: weekly_nvr.get(w, {"new": 0, "returning": 0}) for w in all_weeks},
        "channels":    {w: {ch: weekly_channels[w].get(ch, 0) for ch in top_channels} for w in all_weeks},
        "topChannels": top_channels,
        "geo":         {w: weekly_geo.get(w, {"us": 0, "nonUs": 0}) for w in all_weeks},
        "landingPages": top_landing_pages,
        "events":      {w: weekly_events.get(w, {e: 0 for e in TARGET_EVENTS}) for w in all_weeks},
    }

    print(f"✅  GA4 collected — {len(all_weeks)} weeks, {len(top_channels)} channels")
    return payload

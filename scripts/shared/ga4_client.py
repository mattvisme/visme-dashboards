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
StringFilter = Filter.StringFilter

WEEKS_HISTORY = 156   # 3 years: 104 current + 52 prior-year buffer
TARGET_EVENTS = ["register", "purchase"]


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
                         "visme-marketing-491309-8316da126688.json")
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

    today = date.today()
    if today.weekday() == 6:          # Sunday — today IS the end of a complete week
        last_sunday  = today
        this_monday  = today + timedelta(days=1)   # next Mon (exclusion boundary only)
    else:
        this_monday  = today - timedelta(days=today.weekday())   # Mon of current week
        last_sunday  = this_monday - timedelta(days=1)           # Sun of last complete week
    start_dt = this_monday - timedelta(weeks=WEEKS_HISTORY)

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
    weekly_nvr = defaultdict(lambda: {"new": 0, "returning": 0, "notSet": 0})
    for date_str, nvr, sess in run(["date", "newVsReturning"], ["sessions"]):
        w = _get_monday_str(date_str)
        val = nvr.lower()
        if val == "new":
            key = "new"
        elif val == "returning":
            key = "returning"
        else:
            key = "notSet"
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
    # Always include Affiliates if it has any sessions, even outside the top 15
    if "Affiliates" in all_channels and "Affiliates" not in top_channels:
        top_channels.append("Affiliates")

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

    # 5. Top Landing Pages — www.visme.co only, exclude (not set)
    print("⏳  Pulling landing pages …")
    hostname_filter = FilterExpression(
        filter=Filter(
            field_name="hostName",
            string_filter=StringFilter(
                value="www.visme.co",
                match_type=StringFilter.MatchType.EXACT
            )
        )
    )
    landing_pages_raw = []
    for row in run(["landingPagePlusQueryString"], ["sessions", "newUsers", "bounceRate"],
                   row_limit=500, dim_filter=hostname_filter):
        page, sess, nu, br = row
        if page == "(not set)":
            continue
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
        "nvr":         {w: dict(weekly_nvr.get(w, {"new": 0, "returning": 0, "notSet": 0})) for w in all_weeks},
        "channels":    {w: {ch: weekly_channels[w].get(ch, 0) for ch in top_channels} for w in all_weeks},
        "topChannels": top_channels,
        "geo":         {w: dict(weekly_geo.get(w, {"us": 0, "nonUs": 0})) for w in all_weeks},
        "landingPages": top_landing_pages,
        "events":      {w: dict(weekly_events.get(w, {e: 0 for e in TARGET_EVENTS})) for w in all_weeks},
    }

    print(f"✅  GA4 collected — {len(all_weeks)} weeks, {len(top_channels)} channels")
    return payload


# Per direct instruction: no prior-year data needed, start Jan 2026 and grow
# forward from there as more months/weeks complete — not a fixed lookback
# window. Selectable range is [START_DATE, last complete month/week], and
# grows every time this is re-run.
CHANNEL_PERF_START_DATE     = date(2026, 1, 1)
CHANNEL_PERF_TOP_N_SOURCES  = 20   # per channel per period, matching the reference artifact's cutoff


def _prev_month(y: int, m: int):
    return (y - 1, 12) if m == 1 else (y, m - 1)


def _next_month(y: int, m: int):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _month_bounds(y: int, m: int):
    start = date(y, m, 1)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    end = date(ny, nm, 1) - timedelta(days=1)
    return start, end


def fetch_channel_performance_data(property_id=None, credentials_file=None) -> dict:
    """
    Fetch GA4 sessions by (Default Channel Group x Source/Medium) for:
      - every complete calendar month from CHANNEL_PERF_START_DATE (Jan 2026)
        through the last complete calendar month
      - every complete Mon-Sun ISO week from the Monday on/after
        CHANNEL_PERF_START_DATE through the last complete week

    Both lists grow every time this is re-run — not a fixed lookback window.
    The front end lets the user pick up to 3 months / 4 weeks from these
    lists and compares every selected pair.

    Traffic-side data ONLY. There is no GA4-side "Free"/"Paid" data in this
    payload — that half of the dashboard comes from the Weekly Conversion &
    Signups Google Sheet; see build_channel_performance.py.

    Returns:
      {
        "asOfDate": str,
        "months": {"keys": [...asc...], "labels": {key: label}},
        "weeks":  {"keys": [...asc...], "labels": {key: label}},
        "monthlyTraffic": {channel: {source_medium: {monthKey: sessions}}},
        "weeklyTraffic":  {channel: {source_medium: {weekKey: sessions}}},
        "channelOrder": [channel, ...]  # sorted by total sessions desc, NOT a fixed/hardcoded list
      }
    """
    if property_id is None:
        property_id = os.environ.get("GA4_PROPERTY_ID", "368188880")

    creds = _get_credentials(credentials_file)
    client = BetaAnalyticsDataClient(credentials=creds)
    prop = f"properties/{property_id}"

    def run(start_date: str, end_date: str, row_limit=250_000):
        req = RunReportRequest(
            property=prop,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="sessionDefaultChannelGroup"),
                        Dimension(name="sessionSourceMedium")],
            metrics=[Metric(name="sessions")],
            limit=row_limit,
        )
        for attempt in range(4):
            try:
                resp = client.run_report(req, timeout=120)
                break
            except Exception as e:
                if attempt == 3:
                    raise
                wait = 15 * (2 ** attempt)
                print(f"  GA4 API error (attempt {attempt + 1}/4), retrying in {wait}s: {e}")
                time.sleep(wait)
        return [[d.value for d in r.dimension_values] + [m.value for m in r.metric_values]
                for r in resp.rows]

    def int_(v):
        try:
            return int(float(v))
        except Exception:
            return 0

    today = date.today()

    # ── Complete calendar months, Jan 2026 → last complete month ────────────
    this_month_start = date(today.year, today.month, 1)
    last_complete_month_end = this_month_start - timedelta(days=1)
    y, m = CHANNEL_PERF_START_DATE.year, CHANNEL_PERF_START_DATE.month
    month_ym = []
    while (y, m) <= (last_complete_month_end.year, last_complete_month_end.month):
        month_ym.append((y, m))
        y, m = _next_month(y, m)

    # ── Complete Mon-Sun ISO weeks, Monday on/after Jan 1 2026 → last complete week ──
    start_offset = (0 - CHANNEL_PERF_START_DATE.weekday()) % 7
    first_monday = CHANNEL_PERF_START_DATE + timedelta(days=start_offset)
    this_monday = today - timedelta(days=today.weekday())
    last_complete_week_monday = this_monday - timedelta(days=7)
    week_mondays = []
    d = first_monday
    while d <= last_complete_week_monday:
        week_mondays.append(d)
        d += timedelta(weeks=1)

    month_keys, month_labels = [], {}
    monthly_traffic = defaultdict(lambda: defaultdict(dict))
    print(f"⏳  Pulling channel performance — {len(month_ym)} months …")
    for (yy, mm) in month_ym:
        start, end = _month_bounds(yy, mm)
        key = f"{yy:04d}-{mm:02d}"
        month_keys.append(key)
        month_labels[key] = start.strftime("%b '%y")   # "Jan '26" — abbreviated, per direct instruction (spacing)
        for channel, source_medium, sessions in run(start.isoformat(), end.isoformat()):
            monthly_traffic[channel][source_medium][key] = int_(sessions)

    week_keys, week_labels = [], {}
    weekly_traffic = defaultdict(lambda: defaultdict(dict))
    print(f"⏳  Pulling channel performance — {len(week_mondays)} weeks …")
    for monday in week_mondays:
        sunday = monday + timedelta(days=6)
        key = monday.isoformat()
        week_keys.append(key)
        # "Jul 13 – Jul 19 '26" — year shown once, per direct instruction (spacing)
        mon_short = monday.strftime("%b") + f" {monday.day}"
        week_labels[key] = f"{mon_short} – {_fmt_label(sunday)}"
        for channel, source_medium, sessions in run(monday.isoformat(), sunday.isoformat()):
            weekly_traffic[channel][source_medium][key] = int_(sessions)

    # channelOrder: sorted by total sessions across everything just fetched,
    # descending. Not a fixed/curated list — see README note in the handoff:
    # the reference artifact's fixed 17-channel order was an artifact of only
    # having 3 fixed CSV exports to work with, not a deliberate design choice.
    channel_totals = defaultdict(int)
    for src in (monthly_traffic, weekly_traffic):
        for channel, sm_map in src.items():
            for sm, per_period in sm_map.items():
                channel_totals[channel] += sum(per_period.values())
    channel_order = [c for c, _ in sorted(channel_totals.items(), key=lambda x: -x[1])]

    as_of_date = week_labels[week_keys[-1]] if week_keys else last_complete_month_end.isoformat()

    payload = {
        "asOfDate": as_of_date,
        "propertyId": property_id,
        "months": {"keys": month_keys, "labels": month_labels},
        "weeks": {"keys": week_keys, "labels": week_labels},
        "monthlyTraffic": {ch: dict(sm) for ch, sm in monthly_traffic.items()},
        "weeklyTraffic": {ch: dict(sm) for ch, sm in weekly_traffic.items()},
        "channelOrder": channel_order,
    }
    print(f"✅  Channel performance collected — {len(month_keys)} months, "
          f"{len(week_keys)} weeks, {len(channel_order)} channels")
    return payload


def fetch_paid_search_new_users(property_id=None, credentials_file=None, weeks=156) -> dict:
    """
    Fetch weekly new users from Paid Search channel only.
    Returns dict keyed by week_start (YYYY-MM-DD) → int new users.
    Used by the PPC dashboard for the Free Signups (Paid) metric.
    """
    if property_id is None:
        property_id = os.environ.get("GA4_PROPERTY_ID", "368188880")

    credentials = _get_credentials(credentials_file)
    client = BetaAnalyticsDataClient(credentials=credentials)

    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    start_dt = this_monday - timedelta(weeks=weeks)
    last_sunday = this_monday - timedelta(days=1)

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(
            start_date=start_dt.strftime("%Y-%m-%d"),
            end_date=last_sunday.strftime("%Y-%m-%d"),
        )],
        dimensions=[Dimension(name="date")],
        metrics=[Metric(name="newUsers")],
        dimension_filter=FilterExpression(
            filter=Filter(
                field_name="sessionDefaultChannelGroup",
                in_list_filter=InListFilter(values=["Paid Search"]),
            )
        ),
    )

    this_monday_str = this_monday.strftime("%Y-%m-%d")
    weekly: dict[str, int] = defaultdict(int)

    for attempt in range(3):
        try:
            response = client.run_report(request, timeout=120)
            for row in response.rows:
                date_str = row.dimension_values[0].value
                w = _get_monday_str(date_str)
                if w < this_monday_str:
                    weekly[w] += int(row.metric_values[0].value or 0)
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(15 * (attempt + 1))
            else:
                raise

    return dict(weekly)

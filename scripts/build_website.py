#!/usr/bin/env python3
"""
scripts/build_website.py
Fetches GA4 channel + country traffic data and injects it into website/index.html.

Usage:
    python scripts/build_website.py

Environment variables:
    GA4_CREDENTIALS_JSON   JSON string of service account key (CI/CD)
    GA4_CREDENTIALS_FILE   Path to service account JSON file (local dev)
    GA4_PROPERTY_ID        GA4 property ID (default: 368188880)

# ── WEEK BOUNDARY LOGIC ───────────────────────────────────────────────────────
#
# All weeks are fixed Monday-to-Sunday spans.  Only *complete* weeks appear in
# any view — the current in-progress week is always excluded.
#
# Step 1 — find today's Monday:
#   this_monday = today - timedelta(days=today.weekday())
#   (weekday() returns 0 for Monday … 6 for Sunday)
#
# Step 2 — last complete Sunday is the day before this Monday:
#   last_sunday = this_monday - timedelta(days=1)
#
# Step 3 — 13-week window start is 13 Mondays ago:
#   window_start = this_monday - timedelta(weeks=13)
#   GA4 date range: window_start → last_sunday  (both inclusive)
#
# Example (run on a Wednesday 2025-06-18):
#   this_monday  = 2025-06-16
#   last_sunday  = 2025-06-15  ← end of most recent complete week
#   window_start = 2025-03-17  ← start of the 13th-back Monday
#
# The 13 complete weeks are:
#   Mon 2025-03-17 → Sun 2025-03-23   (week 1, oldest)
#   ...
#   Mon 2025-06-09 → Sun 2025-06-15   (week 13, most recent)
#
# After fetching daily rows from GA4 (dimension: "date"), each date is mapped to
# its week's Monday via _week_monday(date_str).  Weeks whose Monday >= this_monday
# are discarded so a partially-complete week can never appear.
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

REPO_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE     = os.path.join(REPO_ROOT, "website", "index.html")
OUTPUT       = os.path.join(REPO_ROOT, "website", "index.html")
PROPERTY_ID  = os.environ.get("GA4_PROPERTY_ID", "368188880")
WEEKS        = 13

TRACKED_COUNTRIES = [
    "United States", "Canada", "United Kingdom",
    "France", "Mexico", "Spain", "India", "Australia",
]
PRIMARY_CHANNELS = ["Organic Search", "Direct", "Referral", "Paid Search", "Paid AI"]


# ── AUTH ──────────────────────────────────────────────────────────────────────

def _get_credentials():
    """Load service account credentials — same pattern as ga4_client.py."""
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
    for the trailing 13 complete weeks.  See module docstring for full explanation.
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


# ── GA4 RUNNER ────────────────────────────────────────────────────────────────

# ── ORGANIC SOCIAL PLATFORM GROUPING ─────────────────────────────────────────
_FACEBOOK_SOURCES = frozenset({
    "facebook", "facebook.com", "m.facebook.com", "l.facebook.com", "lm.facebook.com",
    "accountscenter.facebook.com", "oauth.facebook.com", "adsmanager.facebook.com",
    "business.facebook.com", "l.messenger.com",
})
_REDDIT_SOURCES   = frozenset({"reddit.com", "old.reddit.com"})
_LINKEDIN_SOURCES = frozenset({"linkedin.com", "linkedin", "lnkd.in", "linkedinad"})
_INSTAGRAM_SOURCES = frozenset({
    "l.instagram.com", "instagram.com", "instagram", "ig",
    "accountscenter.instagram.com",
})
_TWITTER_SOURCES  = frozenset({"t.co", "twitter.com", "twitter", "twitterpost", "x.com", "x"})
_VK_SOURCES       = frozenset({"away.vk.com", "vk.com", "m.vk.com"})

# Named platforms in preferred stack order (bottom → top); Other always appended last.
SOCIAL_PLATFORM_ORDER = ["Facebook", "Pinterest", "Reddit", "LinkedIn", "Instagram", "X/Twitter"]


def _social_platform(source: str):
    """Map a GA4 sessionSource to a social platform name, or None to exclude (VK)."""
    s = source.lower().strip()
    if s in _VK_SOURCES:       return None
    if s in _FACEBOOK_SOURCES: return "Facebook"
    if s in ("pinterest", "pinterest.com") or s.endswith(".pinterest.com"):
        return "Pinterest"
    if s in _REDDIT_SOURCES:   return "Reddit"
    if s in _LINKEDIN_SOURCES: return "LinkedIn"
    if s in _INSTAGRAM_SOURCES: return "Instagram"
    if s in _TWITTER_SOURCES:  return "X/Twitter"
    return "Other"


def _channel_filter(channel_name: str) -> FilterExpression:
    """Build a GA4 FilterExpression matching sessionDefaultChannelGrouping exactly."""
    return FilterExpression(
        filter=Filter(
            field_name="sessionDefaultChannelGrouping",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.EXACT,
                value=channel_name,
            ),
        )
    )


def _medium_filter(medium_value: str) -> FilterExpression:
    """Build a GA4 FilterExpression matching sessionMedium exactly."""
    return FilterExpression(
        filter=Filter(
            field_name="sessionMedium",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.EXACT,
                value=medium_value,
            ),
        )
    )


def _first_user_medium_filter(medium_value: str) -> FilterExpression:
    """Build a GA4 FilterExpression matching firstUserMedium exactly."""
    return FilterExpression(
        filter=Filter(
            field_name="firstUserMedium",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.EXACT,
                value=medium_value,
            ),
        )
    )


def _run(client, prop, start_date, end_date, dimensions, metrics, row_limit=10_000, dimension_filter=None):
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


# ── DATA FETCHES ──────────────────────────────────────────────────────────────

def fetch_traffic_data() -> dict:
    print("=" * 60)
    print("Building website/index.html — GA4 traffic decomposition")
    print("=" * 60)

    start_date, end_date, this_monday_str, as_of_date = _compute_date_range()
    print(f"📅  Date range: {start_date} → {end_date}  (13 complete weeks)")

    creds  = _get_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)
    prop   = f"properties/{PROPERTY_ID}"

    # ── 1. Sessions + Engagement Rate by channel × week (View 1 trend) ───────
    print("⏳  Pulling channel sessions + engagement rate …")
    channel_weekly: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))
    # {week_monday -> {channel -> {sessions, engagementRate}}}
    raw_ch = _run(client, prop, start_date, end_date,
                  ["sessionDefaultChannelGrouping", "date"],
                  ["sessions", "engagementRate"],
                  row_limit=50_000)
    for ch, date_str, sess, eng in raw_ch:
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        prev = channel_weekly[w].get(ch, {"sessions": 0, "engagementRate": 0.0})
        # engagementRate is a ratio 0–1; aggregate as weighted average via sum trick
        prev_sess = prev["sessions"]
        new_sess  = _int(sess)
        total     = prev_sess + new_sess
        prev_eng  = prev["engagementRate"]
        new_eng   = _float(eng)
        avg_eng   = (prev_eng * prev_sess + new_eng * new_sess) / total if total else 0.0
        channel_weekly[w][ch] = {"sessions": total, "engagementRate": round(avg_eng, 4)}

    # ── 2. New Users by first-user channel × week (separate dimension) ────────
    print("⏳  Pulling new users by first-user channel …")
    new_users_by_channel: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    raw_nu = _run(client, prop, start_date, end_date,
                  ["firstUserDefaultChannelGrouping", "date"],
                  ["newUsers"],
                  row_limit=50_000)
    for ch, date_str, nu in raw_nu:
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        new_users_by_channel[w][ch] += _int(nu)

    # ── 3. Country × channel × week (View 2) ─────────────────────────────────
    print("⏳  Pulling country × channel sessions …")
    country_weekly: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )  # {week -> {country -> {channel -> sessions}}}
    raw_geo = _run(client, prop, start_date, end_date,
                   ["country", "sessionDefaultChannelGrouping", "date"],
                   ["sessions"],
                   row_limit=50_000)
    for country, ch, date_str, sess in raw_geo:
        if country not in TRACKED_COUNTRIES:
            continue
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        country_weekly[w][country][ch] += _int(sess)

    # ── 4. Paid AI sessions + engagement × week ──────────────────────────────
    # "Paid AI" lives in a custom channel group (not the default), so
    # sessionDefaultChannelGrouping never returns it.  We identify these
    # sessions by filtering on sessionMedium = 'paid_ai' instead.
    print("⏳  Pulling Paid AI sessions …")
    raw_paid_ai = _run(client, prop, start_date, end_date,
                       ["date"],
                       ["sessions", "engagementRate"],
                       row_limit=10_000,
                       dimension_filter=_medium_filter("paid_ai"))
    for date_str, sess, eng in raw_paid_ai:
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        prev      = channel_weekly[w].get("Paid AI", {"sessions": 0, "engagementRate": 0.0})
        prev_sess = prev["sessions"]
        new_sess  = _int(sess)
        total     = prev_sess + new_sess
        avg_eng   = (prev["engagementRate"] * prev_sess + _float(eng) * new_sess) / total if total else 0.0
        channel_weekly[w]["Paid AI"] = {"sessions": total, "engagementRate": round(avg_eng, 4)}

    # ── 4b. Paid AI new users × week ─────────────────────────────────────────
    raw_paid_ai_nu = _run(client, prop, start_date, end_date,
                          ["date"],
                          ["newUsers"],
                          row_limit=10_000,
                          dimension_filter=_first_user_medium_filter("paid_ai"))
    for date_str, nu in raw_paid_ai_nu:
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        new_users_by_channel[w]["Paid AI"] += _int(nu)

    # ── 4c. Paid AI country × week (for country breakdown charts) ────────────
    raw_paid_ai_geo = _run(client, prop, start_date, end_date,
                           ["country", "date"],
                           ["sessions"],
                           row_limit=10_000,
                           dimension_filter=_medium_filter("paid_ai"))
    for country, date_str, sess in raw_paid_ai_geo:
        if country not in TRACKED_COUNTRIES:
            continue
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        country_weekly[w][country]["Paid AI"] += _int(sess)

    # ── 5. AI Assistant source × week (View 5) ───────────────────────────────
    print("⏳  Pulling AI Assistant sessions by source …")
    ai_source_weekly: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # {source -> {week_monday -> sessions}}
    raw_ai = _run(client, prop, start_date, end_date,
                  ["sessionSource", "date"],
                  ["sessions"],
                  row_limit=2000,
                  dimension_filter=_channel_filter("AI Assistant"))
    for source, date_str, sess in raw_ai:
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        ai_source_weekly[source][w] += _int(sess)

    # ── 5. Affiliate source × week (View 6) ──────────────────────────────────
    print("⏳  Pulling Affiliate sessions by source …")
    aff_source_weekly: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    raw_aff = _run(client, prop, start_date, end_date,
                   ["sessionSource", "date"],
                   ["sessions"],
                   row_limit=2000,
                   dimension_filter=_channel_filter("Affiliates"))
    for source, date_str, sess in raw_aff:
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        aff_source_weekly[source][w] += _int(sess)

    # ── 6. Organic Social source × week (View 7) ─────────────────────────────
    print("⏳  Pulling Organic Social sessions by source …")
    os_platform_weekly: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # row_limit must be large: 13 weeks × 7 days × many sources easily exceeds 200
    raw_os = _run(client, prop, start_date, end_date,
                  ["sessionSource", "date"],
                  ["sessions"],
                  row_limit=5000,
                  dimension_filter=_channel_filter("Organic Social"))
    for source, date_str, sess in raw_os:
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        platform = _social_platform(source)
        if platform is None:
            continue
        os_platform_weekly[platform][w] += _int(sess)

    # ── 7. Total sessions per week (for unattributed gap calculation) ───────────
    # ~3% of sessions have no sessionDefaultChannelGrouping assignment.
    # These never appear in the channel dimension query, so we fetch total
    # sessions separately and expose the gap as unattributedWeekly.
    print("⏳  Pulling total sessions per week …")
    total_weekly: dict[str, int] = defaultdict(int)
    raw_total = _run(client, prop, start_date, end_date,
                     ["date"], ["sessions"], row_limit=10_000)
    for date_str, sess in raw_total:
        w = _week_monday(date_str)
        if w >= this_monday_str:
            continue
        total_weekly[w] += _int(sess)

    # ── 8. Latest-week snapshot — two most recent complete weeks (View 3) ─────
    # We already have channel_weekly; derive from it after assembling week list.

    # ── 8. Unassigned + (not set) over 13 weeks (View 4) ─────────────────────
    # Also derived from channel_weekly.

    # ── Assemble sorted week list ─────────────────────────────────────────────
    all_weeks = sorted(
        w for w in set(channel_weekly.keys()) | set(new_users_by_channel.keys())
        if w < this_monday_str
    )
    # Keep only the last 13
    all_weeks = all_weeks[-WEEKS:]

    labels = [_fmt_label(w) for w in all_weeks]

    # ── Build channelWeekly ───────────────────────────────────────────────────
    all_channels: set[str] = set()
    for w in all_weeks:
        all_channels.update(channel_weekly[w].keys())
    all_channels_sorted = sorted(
        all_channels,
        key=lambda c: -sum(channel_weekly[w].get(c, {}).get("sessions", 0) for w in all_weeks),
    )

    channel_weekly_out: dict[str, list] = {}
    engagement_by_channel: dict[str, list] = {}
    for ch in all_channels_sorted:
        channel_weekly_out[ch] = [channel_weekly[w].get(ch, {}).get("sessions", 0) for w in all_weeks]
        engagement_by_channel[ch] = [channel_weekly[w].get(ch, {}).get("engagementRate", 0.0) for w in all_weeks]

    # ── Build newUsersByChannel ───────────────────────────────────────────────
    all_nu_channels: set[str] = set()
    for w in all_weeks:
        all_nu_channels.update(new_users_by_channel[w].keys())
    new_users_out: dict[str, list] = {
        ch: [new_users_by_channel[w].get(ch, 0) for w in all_weeks]
        for ch in all_nu_channels
    }

    # ── Build countryChannelWeekly ────────────────────────────────────────────
    # {country -> {channel -> [sessions per week]}}
    country_channel_weekly_out: dict[str, dict[str, list]] = {}
    for country in TRACKED_COUNTRIES:
        country_channel_weekly_out[country] = {}
        for ch in PRIMARY_CHANNELS:
            series = [country_weekly[w][country].get(ch, 0) for w in all_weeks]
            if any(v > 0 for v in series):
                country_channel_weekly_out[country][ch] = series

    # Country summary table: latest week + prior week per (country, channel)
    latest_w = all_weeks[-1] if all_weeks else None
    prior_w  = all_weeks[-2] if len(all_weeks) >= 2 else None
    country_table = []
    for country in TRACKED_COUNTRIES:
        for ch in PRIMARY_CHANNELS:
            this_sess = country_weekly.get(latest_w, {}).get(country, {}).get(ch, 0) if latest_w else 0
            last_sess = country_weekly.get(prior_w, {}).get(country, {}).get(ch, 0) if prior_w else 0
            if this_sess == 0 and last_sess == 0:
                continue
            country_table.append({
                "country": country,
                "channel": ch,
                "thisWeek": this_sess,
                "lastWeek": last_sess,
            })
    country_table.sort(key=lambda r: -r["thisWeek"])

    # ── Build latestWeekSnapshot ──────────────────────────────────────────────
    snapshot = []
    for ch in all_channels_sorted:
        this_sess = channel_weekly.get(latest_w, {}).get(ch, {}).get("sessions", 0) if latest_w else 0
        last_sess = channel_weekly.get(prior_w, {}).get(ch, {}).get("sessions", 0) if prior_w else 0
        if this_sess == 0 and last_sess == 0:
            continue
        snapshot.append({
            "channel": ch,
            "thisWeek": this_sess,
            "lastWeek": last_sess,
        })
    snapshot.sort(key=lambda r: -r["thisWeek"])

    # ── Build aiAssistantWeekly ───────────────────────────────────────────────
    ai_sources_sorted = sorted(
        ai_source_weekly.keys(),
        key=lambda s: -sum(ai_source_weekly[s].get(w, 0) for w in all_weeks),
    )
    ai_assistant_weekly_out: dict[str, list] = {
        s: [ai_source_weekly[s].get(w, 0) for w in all_weeks]
        for s in ai_sources_sorted
    }

    # ── Build affiliateWeekly ─────────────────────────────────────────────────
    aff_sources_sorted = sorted(
        aff_source_weekly.keys(),
        key=lambda s: -sum(aff_source_weekly[s].get(w, 0) for w in all_weeks),
    )
    affiliate_weekly_out: dict[str, list] = {
        s: [aff_source_weekly[s].get(w, 0) for w in all_weeks]
        for s in aff_sources_sorted
    }

    # ── Build organicSocialWeekly ─────────────────────────────────────────────
    # Named platforms sorted by total sessions desc; Other appended last if present.
    named_sorted = sorted(
        [p for p in SOCIAL_PLATFORM_ORDER
         if any(os_platform_weekly[p].get(w, 0) > 0 for w in all_weeks)],
        key=lambda p: -sum(os_platform_weekly[p].get(w, 0) for w in all_weeks),
    )
    organic_social_weekly_out: dict[str, list] = {
        p: [os_platform_weekly[p].get(w, 0) for w in all_weeks]
        for p in named_sorted
    }
    if any(os_platform_weekly["Other"].get(w, 0) > 0 for w in all_weeks):
        organic_social_weekly_out["Other"] = [
            os_platform_weekly["Other"].get(w, 0) for w in all_weeks
        ]

    # ── Build unassignedWeekly ────────────────────────────────────────────────
    unassigned_series = [
        channel_weekly[w].get("Unassigned", {}).get("sessions", 0)
        for w in all_weeks
    ]

    # ── Build notSetCount ─────────────────────────────────────────────────────
    not_set_count = sum(
        channel_weekly[w].get("(not set)", {}).get("sessions", 0)
        for w in all_weeks
    )

    # ── Build unattributedWeekly ──────────────────────────────────────────────
    # Sessions that GA4 cannot assign to any channel group never appear in
    # the sessionDefaultChannelGrouping dimension query (~3% of total).
    # Computed as: total_sessions_this_week - sum_of_all_named_channel_sessions.
    unattributed_weekly = []
    for w in all_weeks:
        named_sum = sum(
            channel_weekly[w].get(ch, {}).get("sessions", 0)
            for ch in all_channels
        )
        gap = max(0, total_weekly.get(w, 0) - named_sum)
        unattributed_weekly.append(gap)
    unattributed_total = sum(unattributed_weekly)
    print(f"  Unattributed sessions across {len(all_weeks)} weeks: {unattributed_total:,} "
          f"({unattributed_total / max(1, sum(total_weekly.get(w,0) for w in all_weeks)) * 100:.1f}%)")

    payload = {
        "dataAsOfDate":        as_of_date,
        "weeks":               all_weeks,
        "weekLabels":          labels,
        "allChannels":         all_channels_sorted,
        "channelWeekly":       channel_weekly_out,
        "engagementByChannel": engagement_by_channel,
        "newUsersByChannel":   new_users_out,
        "countryChannelWeekly": country_channel_weekly_out,
        "countryTable":        country_table,
        "latestWeekSnapshot":  snapshot,
        "aiAssistantWeekly":   ai_assistant_weekly_out,
        "affiliateWeekly":     affiliate_weekly_out,
        "organicSocialWeekly": organic_social_weekly_out,
        "unassignedWeekly":    unassigned_series,
        "notSetCount":         not_set_count,
        "unattributedWeekly":  unattributed_weekly,
        "primaryChannels":     PRIMARY_CHANNELS,
        "trackedCountries":    TRACKED_COUNTRIES,
    }

    print(f"✅  Collected — {len(all_weeks)} weeks, {len(all_channels_sorted)} channels, "
          f"{len(ai_sources_sorted)} AI sources, {len(aff_sources_sorted)} affiliate sources, "
          f"{len(organic_social_weekly_out)} social platforms")
    return payload


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    try:
        data = fetch_traffic_data()
    except Exception as exc:
        print(f"\n❌  GA4 fetch failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        inject_data(
            template_path=TEMPLATE,
            data_dict={"TRAFFIC": data},
            output_path=OUTPUT,
        )
    except Exception as exc:
        print(f"\n❌  HTML injection failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()

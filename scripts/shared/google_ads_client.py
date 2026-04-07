#!/usr/bin/env python3
"""
scripts/shared/google_ads_client.py
Pulls all data needed for the PPC dashboard from the Google Ads API.

Dependencies: pip install google-ads

Auth uses the same service-account JSON as the rest of the build system:
  GA4_CREDENTIALS_JSON  — raw JSON string (GitHub Actions)
  GA4_CREDENTIALS_FILE  — local file path (dev)

Manager Customer ID : 4091490058
Visme Customer ID   : 2405880186
"""

import os
import tempfile
from datetime import date, timedelta
from collections import defaultdict

import google.auth
from google.ads.googleads.client import GoogleAdsClient

# ─── US STATE CRITERION ID MAP ────────────────────────────────────────────────
US_STATES = {
    21137: "Alabama",        21138: "Alaska",         21139: "Arizona",
    21140: "Arkansas",       21141: "California",     21142: "Colorado",
    21143: "Connecticut",    21144: "Delaware",        21145: "Florida",
    21146: "Georgia",        21147: "Hawaii",          21148: "Idaho",
    21149: "Illinois",       21150: "Indiana",         21151: "Iowa",
    21152: "Kansas",         21153: "Kentucky",        21154: "Louisiana",
    21155: "Maine",          21156: "Maryland",        21157: "Massachusetts",
    21158: "Michigan",       21159: "Minnesota",       21160: "Mississippi",
    21161: "Missouri",       21162: "Montana",         21163: "Nebraska",
    21164: "Nevada",         21165: "New Hampshire",   21166: "New Jersey",
    21167: "New Mexico",     21168: "New York",        21169: "North Carolina",
    21170: "North Dakota",   21171: "Ohio",            21172: "Oklahoma",
    21173: "Oregon",         21174: "Pennsylvania",    21175: "Rhode Island",
    21176: "South Carolina", 21177: "South Dakota",    21178: "Tennessee",
    21179: "Texas",          21180: "Utah",            21181: "Vermont",
    21182: "Virginia",       21183: "Washington",      21184: "West Virginia",
    21185: "Wisconsin",      21186: "Wyoming",         21187: "District of Columbia",
}

# ─── CHANNEL TYPE MAP ─────────────────────────────────────────────────────────
_CHANNEL_MAP = {
    "SEARCH":          "Search",
    "DISPLAY":         "Display",
    "VIDEO":           "Video",
    "SHOPPING":        "Shopping",
    "PERFORMANCE_MAX": "PMax",
}

# ─── MATCH TYPE MAP ───────────────────────────────────────────────────────────
_MATCH_MAP = {
    "EXACT":  "Exact",
    "PHRASE": "Phrase",
    "BROAD":  "Broad",
}


# ─── CREDENTIALS ──────────────────────────────────────────────────────────────

def _resolve_credentials_file():
    """Return path to a service-account JSON file (writes tempfile if needed)."""
    creds_json = os.environ.get("GA4_CREDENTIALS_JSON")
    if creds_json:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(creds_json)
        tmp.close()
        return tmp.name
    return os.environ.get(
        "GA4_CREDENTIALS_FILE",
        os.path.join(os.path.expanduser("~"), "Downloads",
                     "visme-marketing-491309-47059dacd5b9.json"),
    )


# ─── DATE RANGE ───────────────────────────────────────────────────────────────

def _get_date_range(weeks=156):
    today       = date.today()
    this_monday = today - timedelta(days=today.weekday())
    last_sunday = this_monday - timedelta(days=1)
    start_dt    = this_monday - timedelta(weeks=weeks)
    return (
        start_dt.strftime("%Y-%m-%d"),
        last_sunday.strftime("%Y-%m-%d"),
        this_monday.strftime("%Y-%m-%d"),
    )


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _micros(v):
    return round(float(v) / 1_000_000, 2)

def _int(v):
    try:    return int(float(v))
    except: return 0

def _float(v, decimals=2):
    try:    return round(float(v), decimals)
    except: return 0.0

def _stream_rows(client, customer_id, query):
    service = client.get_service("GoogleAdsService")
    stream  = service.search_stream(customer_id=customer_id, query=query)
    rows = []
    for batch in stream:
        for row in batch.results:
            rows.append(row)
    return rows


# ─── FUNCTION 1: fetch_weekly_google ─────────────────────────────────────────

def fetch_weekly_google(client, customer_id):
    """Weekly account-level totals. One dict per complete week, oldest first."""
    start, end, this_monday = _get_date_range()
    query = f"""
        SELECT
          segments.week,
          metrics.cost_micros,
          metrics.clicks,
          metrics.impressions,
          metrics.conversions
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND campaign.status = 'ENABLED'
    """
    rows = _stream_rows(client, customer_id, query)

    agg = defaultdict(lambda: {"cost": 0, "clicks": 0, "impressions": 0, "conversions": 0.0})
    for row in rows:
        w = row.segments.week
        if w >= this_monday:
            continue
        agg[w]["cost"]        += row.metrics.cost_micros
        agg[w]["clicks"]      += _int(row.metrics.clicks)
        agg[w]["impressions"] += _int(row.metrics.impressions)
        agg[w]["conversions"] += _float(row.metrics.conversions)

    result = []
    for week_start in sorted(agg):
        d        = date.fromisoformat(week_start)
        week_end = (d + timedelta(days=6)).isoformat()
        a        = agg[week_start]
        result.append({
            "week_start":    week_start,
            "week_end":      week_end,
            "label":         f"{d.month}/{d.day}",
            "g_spend":       _micros(a["cost"]),
            "g_clicks":      a["clicks"],
            "g_impressions": a["impressions"],
            "g_conversions": round(a["conversions"], 2),
        })
    return result


# ─── FUNCTION 2: fetch_campaigns_google ──────────────────────────────────────

def fetch_campaigns_google(client, customer_id):
    """Per-campaign, per-week rows. Oldest first."""
    start, end, this_monday = _get_date_range()
    query = f"""
        SELECT
          segments.week,
          campaign.name,
          campaign.status,
          campaign.advertising_channel_type,
          metrics.cost_micros,
          metrics.clicks,
          metrics.impressions,
          metrics.conversions
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND campaign.status IN ('ENABLED', 'PAUSED')
    """
    rows = _stream_rows(client, customer_id, query)

    agg = {}
    for row in rows:
        w = row.segments.week
        if w >= this_monday:
            continue
        key = (w, row.campaign.name)
        if key not in agg:
            agg[key] = {
                "week":        w,
                "name":        row.campaign.name,
                "status":      row.campaign.status.name,
                "type":        _CHANNEL_MAP.get(row.campaign.advertising_channel_type.name, "Other"),
                "spend":       0.0,
                "clicks":      0,
                "impressions": 0,
                "conversions": 0.0,
            }
        agg[key]["spend"]       += _micros(row.metrics.cost_micros)
        agg[key]["clicks"]      += _int(row.metrics.clicks)
        agg[key]["impressions"] += _int(row.metrics.impressions)
        agg[key]["conversions"] += _float(row.metrics.conversions)

    result = []
    for key in sorted(agg):
        a = agg[key]
        a["spend"]       = round(a["spend"], 2)
        a["conversions"] = round(a["conversions"], 2)
        result.append(a)
    return result


# ─── FUNCTION 3: fetch_ads_google ────────────────────────────────────────────

def fetch_ads_google(client, customer_id):
    """RSA ad performance aggregated over full date window. Sorted by cost desc."""
    start, end, _ = _get_date_range()
    query = f"""
        SELECT
          campaign.name,
          ad_group.name,
          ad_group_ad.ad.responsive_search_ad.headlines,
          ad_group_ad.ad.responsive_search_ad.descriptions,
          ad_group_ad.ad.final_urls,
          ad_group_ad.status,
          metrics.clicks,
          metrics.impressions,
          metrics.conversions,
          metrics.cost_micros
        FROM ad_group_ad
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND ad_group_ad.status IN ('ENABLED', 'PAUSED')
          AND ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
    """
    rows = _stream_rows(client, customer_id, query)

    agg = {}
    for row in rows:
        ad         = row.ad_group_ad.ad
        headlines  = [h.text for h in ad.responsive_search_ad.headlines] if ad.responsive_search_ad.headlines else []
        descs      = [d.text for d in ad.responsive_search_ad.descriptions] if ad.responsive_search_ad.descriptions else []
        h1 = headlines[0] if len(headlines) > 0 else ""
        h2 = headlines[1] if len(headlines) > 1 else ""
        h3 = headlines[2] if len(headlines) > 2 else ""
        raw_url = ad.final_urls[0] if ad.final_urls else ""
        url = raw_url.replace("https://www.visme.co", "").replace("https://visme.co", "") or "/"

        key = (row.campaign.name, row.ad_group.name, h1, h2, h3, url)
        if key not in agg:
            agg[key] = {
                "campaign": row.campaign.name, "ad_group": row.ad_group.name,
                "headline1": h1, "headline2": h2, "headline3": h3,
                "description": descs[0] if descs else "",
                "url": url, "status": row.ad_group_ad.status.name,
                "clicks": 0, "impressions": 0, "conversions": 0.0, "cost": 0.0,
            }
        agg[key]["clicks"]      += _int(row.metrics.clicks)
        agg[key]["impressions"] += _int(row.metrics.impressions)
        agg[key]["conversions"] += _float(row.metrics.conversions)
        agg[key]["cost"]        += _micros(row.metrics.cost_micros)

    result = []
    for a in agg.values():
        a["cost"]        = round(a["cost"], 2)
        a["conversions"] = round(a["conversions"], 2)
        a["conv_rate"]   = round(a["conversions"] / a["clicks"],  4) if a["clicks"]      > 0 else 0.0
        a["cpa"]         = round(a["cost"]        / a["conversions"], 2) if a["conversions"] > 0 else 0.0
        result.append(a)
    return sorted(result, key=lambda x: x["cost"], reverse=True)


# ─── FUNCTION 4: fetch_keywords_google ───────────────────────────────────────

def fetch_keywords_google(client, customer_id):
    """Returns (kw_summary, kw_weekly)."""
    start, end, this_monday = _get_date_range(weeks=156)
    start_26, _, _          = _get_date_range(weeks=26)

    def _kw_query(date_filter, with_week=False):
        week_field = "segments.week," if with_week else ""
        return f"""
            SELECT
              {week_field}
              ad_group_criterion.keyword.text,
              ad_group_criterion.keyword.match_type,
              campaign.name,
              ad_group.name,
              metrics.cost_micros,
              metrics.clicks,
              metrics.impressions,
              metrics.conversions
            FROM keyword_view
            WHERE {date_filter}
              AND ad_group_criterion.status IN ('ENABLED', 'PAUSED')
              AND campaign.status IN ('ENABLED', 'PAUSED')
        """

    # — Summary (full window) —
    agg_s = {}
    for row in _stream_rows(client, customer_id, _kw_query(f"segments.date BETWEEN '{start}' AND '{end}'")):
        kw  = row.ad_group_criterion.keyword.text
        mt  = _MATCH_MAP.get(row.ad_group_criterion.keyword.match_type.name, "")
        key = (kw, mt, row.campaign.name, row.ad_group.name)
        if key not in agg_s:
            agg_s[key] = {"keyword": kw, "match_type": mt, "campaign": row.campaign.name,
                          "ad_group": row.ad_group.name, "spend": 0.0, "clicks": 0,
                          "impressions": 0, "conversions": 0.0}
        agg_s[key]["spend"]       += _micros(row.metrics.cost_micros)
        agg_s[key]["clicks"]      += _int(row.metrics.clicks)
        agg_s[key]["impressions"] += _int(row.metrics.impressions)
        agg_s[key]["conversions"] += _float(row.metrics.conversions)

    kw_summary = []
    for a in agg_s.values():
        a["spend"] = round(a["spend"], 2); a["conversions"] = round(a["conversions"], 2)
        a["ctr"]       = round(a["clicks"] / a["impressions"], 4) if a["impressions"] > 0 else 0.0
        a["cpa"]       = round(a["spend"]  / a["conversions"],  2) if a["conversions"] > 0 else 0.0
        a["conv_rate"] = round(a["conversions"] / a["clicks"],  4) if a["clicks"]      > 0 else 0.0
        kw_summary.append(a)
    kw_summary.sort(key=lambda x: x["spend"], reverse=True)

    # — Weekly (last 26 weeks) —
    agg_w = {}
    for row in _stream_rows(client, customer_id,
                            _kw_query(f"segments.date BETWEEN '{start_26}' AND '{end}'", with_week=True)):
        w   = row.segments.week
        if w >= this_monday:
            continue
        kw  = row.ad_group_criterion.keyword.text
        mt  = _MATCH_MAP.get(row.ad_group_criterion.keyword.match_type.name, "")
        key = (w, kw, mt, row.campaign.name, row.ad_group.name)
        if key not in agg_w:
            agg_w[key] = {"week": w, "keyword": kw, "match_type": mt,
                          "campaign": row.campaign.name, "ad_group": row.ad_group.name,
                          "spend": 0.0, "clicks": 0, "impressions": 0, "conversions": 0.0}
        agg_w[key]["spend"]       += _micros(row.metrics.cost_micros)
        agg_w[key]["clicks"]      += _int(row.metrics.clicks)
        agg_w[key]["impressions"] += _int(row.metrics.impressions)
        agg_w[key]["conversions"] += _float(row.metrics.conversions)

    kw_weekly = []
    for a in sorted(agg_w.values(), key=lambda x: (x["week"], x["keyword"])):
        a["spend"] = round(a["spend"], 2); a["conversions"] = round(a["conversions"], 2)
        a["ctr"] = round(a["clicks"] / a["impressions"], 4) if a["impressions"] > 0 else 0.0
        kw_weekly.append(a)

    return kw_summary, kw_weekly


# ─── FUNCTION 5: fetch_geo_google ────────────────────────────────────────────

def fetch_geo_google(client, customer_id):
    """US state performance by month. Returns dict keyed by YYYY-MM."""
    start, end, _ = _get_date_range()
    query = f"""
        SELECT
          segments.month,
          geographic_view.country_criterion_id,
          metrics.cost_micros,
          metrics.clicks,
          metrics.conversions
        FROM geographic_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND geographic_view.country_criterion_id = 2840
    """
    rows = _stream_rows(client, customer_id, query)

    agg = defaultdict(lambda: defaultdict(lambda: {"cost": 0, "clicks": 0, "conversions": 0.0}))
    for row in rows:
        month   = row.segments.month[:7]
        crit_id = row.geographic_view.country_criterion_id
        agg[month][crit_id]["cost"]        += row.metrics.cost_micros
        agg[month][crit_id]["clicks"]      += _int(row.metrics.clicks)
        agg[month][crit_id]["conversions"] += _float(row.metrics.conversions)

    result = {}
    for month in sorted(agg):
        states = [
            {"state": US_STATES[cid], "spend": _micros(a["cost"]),
             "clicks": a["clicks"], "conversions": round(a["conversions"], 2)}
            for cid, a in agg[month].items()
            if cid in US_STATES
        ]
        states.sort(key=lambda x: x["spend"], reverse=True)
        result[month] = states
    return result


# ─── FUNCTION 6: fetch_budgets_google ────────────────────────────────────────

def fetch_budgets_google(client, customer_id):
    """Monthly budget vs spend. Returns dict keyed by YYYY-MM."""
    start, end, _ = _get_date_range()
    query = f"""
        SELECT
          campaign.name,
          campaign_budget.amount_micros,
          segments.month,
          metrics.cost_micros
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND campaign.status = 'ENABLED'
    """
    rows = _stream_rows(client, customer_id, query)

    agg = defaultdict(lambda: {"budget": 0.0, "spend": 0.0})
    for row in rows:
        month = row.segments.month[:7]
        agg[month]["budget"] += _micros(row.campaign_budget.amount_micros)
        agg[month]["spend"]  += _micros(row.metrics.cost_micros)

    return {m: {"budget": round(v["budget"], 2), "spend": round(v["spend"], 2)}
            for m, v in sorted(agg.items())}


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def fetch_all_google_ads(developer_token, credentials_file, manager_id, customer_id):
    """
    Authenticate and call all 6 fetch functions.
    Each is wrapped in try/except — failures return [] or {} so the build
    never aborts on a single query error.
    """
    credentials, _ = google.auth.load_credentials_from_file(
        credentials_file,
        scopes=["https://www.googleapis.com/auth/adwords"],
    )
    client = GoogleAdsClient(
        credentials=credentials,
        developer_token=developer_token,
        login_customer_id=manager_id,
    )

    print("⏳ Google Ads: weekly totals...")
    try:
        weekly = fetch_weekly_google(client, customer_id)
        print(f"  → {len(weekly)} complete weeks")
    except Exception as e:
        print(f"  ⚠️  weekly failed: {e}"); weekly = []

    print("⏳ Google Ads: campaigns...")
    try:
        camps = fetch_campaigns_google(client, customer_id)
        print(f"  → {len(camps)} campaign-week rows")
    except Exception as e:
        print(f"  ⚠️  campaigns failed: {e}"); camps = []

    print("⏳ Google Ads: ads...")
    try:
        ads = fetch_ads_google(client, customer_id)
        print(f"  → {len(ads)} ads")
    except Exception as e:
        print(f"  ⚠️  ads failed: {e}"); ads = []

    print("⏳ Google Ads: keywords...")
    try:
        kw, kw_weekly = fetch_keywords_google(client, customer_id)
        print(f"  → {len(kw)} keywords, {len(kw_weekly)} keyword-week rows")
    except Exception as e:
        print(f"  ⚠️  keywords failed: {e}"); kw, kw_weekly = [], []

    print("⏳ Google Ads: geography...")
    try:
        geo = fetch_geo_google(client, customer_id)
        print(f"  → {sum(len(v) for v in geo.values())} state-month entries")
    except Exception as e:
        print(f"  ⚠️  geography failed: {e}"); geo = {}

    print("⏳ Google Ads: budgets...")
    try:
        budgets = fetch_budgets_google(client, customer_id)
        print(f"  → {len(budgets)} months")
    except Exception as e:
        print(f"  ⚠️  budgets failed: {e}"); budgets = {}

    return {
        "weekly":    weekly,
        "camps":     camps,
        "ads":       ads,
        "kw":        kw,
        "kw_weekly": kw_weekly,
        "geo":       geo,
        "budgets":   budgets,
        "build_date": date.today().isoformat(),
    }

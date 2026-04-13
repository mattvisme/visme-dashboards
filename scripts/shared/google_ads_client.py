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
from google.oauth2.credentials import Credentials

# ─── CONSTANTS ────────────────────────────────────────────────────────────────

CUSTOMER_ID = "2405880186"  # Visme — no dashes

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
    "PERFORMANCE_MAX": "Performance max",
    "DEMAND_GEN":      "Demand gen",
}
_CHANNEL_INT = {2: "SEARCH", 3: "DISPLAY", 4: "SHOPPING", 6: "VIDEO",
                10: "PERFORMANCE_MAX", 14: "DEMAND_GEN"}

# ─── STATUS MAP ───────────────────────────────────────────────────────────────
_STATUS_MAP = {
    "ENABLED": "Active",
    "PAUSED":  "Paused",
}
_STATUS_INT = {2: "ENABLED", 3: "PAUSED", 4: "REMOVED"}

# ─── MATCH TYPE MAP ───────────────────────────────────────────────────────────
_MATCH_MAP = {
    "EXACT":  "Exact",
    "PHRASE": "Phrase",
    "BROAD":  "Broad",
}
_MATCH_INT = {2: "EXACT", 3: "PHRASE", 4: "BROAD"}


def _enum_name(field, int_map):
    """Return the string name of a proto enum field, handling both enum and int."""
    try:
        return field.name
    except AttributeError:
        return int_map.get(int(field), str(field))


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
                     "visme-marketing-491309-8316da126688.json"),
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

def fetch_weekly_google(client):
    """Weekly account-level totals. One dict per complete week, oldest first."""
    start, end, this_monday = _get_date_range(156)
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
    rows = _stream_rows(client, CUSTOMER_ID, query)

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

def fetch_campaigns_google(client):
    """Per-campaign, per-week rows. Oldest first."""
    start, end, this_monday = _get_date_range(156)
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
    rows = _stream_rows(client, CUSTOMER_ID, query)

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
                "status":      _STATUS_MAP.get(_enum_name(row.campaign.status, _STATUS_INT), "Unknown"),
                "type":        _CHANNEL_MAP.get(_enum_name(row.campaign.advertising_channel_type, _CHANNEL_INT), "Other"),
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

def fetch_ads_google(client):
    """RSA ad performance aggregated over last 26 weeks. Sorted by cost desc."""
    start, end, _ = _get_date_range(26)
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
          metrics.cost_micros,
          metrics.cost_per_conversion,
          metrics.all_conversions_from_interactions_rate
        FROM ad_group_ad
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND ad_group_ad.status IN ('ENABLED', 'PAUSED')
          AND ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
    """
    rows = _stream_rows(client, CUSTOMER_ID, query)

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
                "url": url, "status": _STATUS_MAP.get(_enum_name(row.ad_group_ad.status, _STATUS_INT), "Unknown"),
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

def fetch_keywords_google(client):
    """Returns (kw_summary, kw_weekly). Both windows use last 26 weeks."""
    start_26, end, this_monday = _get_date_range(26)

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
              metrics.conversions,
              metrics.cost_per_conversion,
              metrics.all_conversions_from_interactions_rate
            FROM keyword_view
            WHERE {date_filter}
              AND ad_group_criterion.status IN ('ENABLED', 'PAUSED')
        """

    # — Summary (last 26 weeks) —
    agg_s = {}
    for row in _stream_rows(client, CUSTOMER_ID,
                            _kw_query(f"segments.date BETWEEN '{start_26}' AND '{end}'")):
        kw  = row.ad_group_criterion.keyword.text
        mt  = _MATCH_MAP.get(_enum_name(row.ad_group_criterion.keyword.match_type, _MATCH_INT), "")
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
    kw_summary = kw_summary[:500]   # cap to top 500 keywords by spend

    # — Weekly (last 26 weeks) —
    agg_w = {}
    for row in _stream_rows(client, CUSTOMER_ID,
                            _kw_query(f"segments.date BETWEEN '{start_26}' AND '{end}'", with_week=True)):
        w   = row.segments.week
        if w >= this_monday:
            continue
        kw  = row.ad_group_criterion.keyword.text
        mt  = _MATCH_MAP.get(_enum_name(row.ad_group_criterion.keyword.match_type, _MATCH_INT), "")
        key = (w, kw, mt, row.campaign.name, row.ad_group.name)
        if key not in agg_w:
            agg_w[key] = {"week": w, "keyword": kw, "match_type": mt,
                          "campaign": row.campaign.name, "ad_group": row.ad_group.name,
                          "spend": 0.0, "clicks": 0, "impressions": 0, "conversions": 0.0}
        agg_w[key]["spend"]       += _micros(row.metrics.cost_micros)
        agg_w[key]["clicks"]      += _int(row.metrics.clicks)
        agg_w[key]["impressions"] += _int(row.metrics.impressions)
        agg_w[key]["conversions"] += _float(row.metrics.conversions)

    # Only keep weekly rows for keywords in the top-500 summary
    top_kw_keys = {(k["keyword"], k["match_type"], k["campaign"], k["ad_group"])
                   for k in kw_summary}
    kw_weekly = []
    for a in sorted(agg_w.values(), key=lambda x: (x["week"], x["keyword"])):
        if (a["keyword"], a["match_type"], a["campaign"], a["ad_group"]) not in top_kw_keys:
            continue
        a["spend"] = round(a["spend"], 2); a["conversions"] = round(a["conversions"], 2)
        a["ctr"] = round(a["clicks"] / a["impressions"], 4) if a["impressions"] > 0 else 0.0
        kw_weekly.append(a)

    return kw_summary, kw_weekly


# ─── FUNCTION 5: fetch_geo_google ────────────────────────────────────────────

def fetch_geo_google(client):
    """US state performance aggregated over last 26 weeks. Returns dict keyed by state name."""
    start, end, _ = _get_date_range(26)
    query = f"""
        SELECT
          geographic_view.location_type,
          geographic_view.country_criterion_id,
          segments.geo_target_region,
          metrics.cost_micros,
          metrics.clicks,
          metrics.conversions
        FROM geographic_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
          AND geographic_view.country_criterion_id = 2840
    """
    rows = _stream_rows(client, CUSTOMER_ID, query)

    agg = defaultdict(lambda: {"cost": 0, "clicks": 0, "conversions": 0.0})
    for row in rows:
        # geo_target_region is a resource name like "geoTargetConstants/21137"
        region = row.segments.geo_target_region
        try:
            crit_id = int(str(region).rsplit("/", 1)[-1])
        except (ValueError, AttributeError):
            continue
        if crit_id not in US_STATES:
            continue
        state = US_STATES[crit_id]
        agg[state]["cost"]        += row.metrics.cost_micros
        agg[state]["clicks"]      += _int(row.metrics.clicks)
        agg[state]["conversions"] += _float(row.metrics.conversions)

    result = {}
    for state, a in agg.items():
        spend = _micros(a["cost"])
        convs = round(a["conversions"], 2)
        clks  = a["clicks"]
        result[state] = {
            "g_spend":     spend,
            "g_clicks":    clks,
            "g_conversions": convs,
            "g_cpa":       round(spend / convs, 2) if convs > 0 else 0.0,
            "g_conv_rate": round(convs / clks,  4) if clks  > 0 else 0.0,
        }
    return result


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def fetch_all_google(developer_token, credentials_file, manager_id, customer_id,
                     client_id=None, client_secret=None, refresh_token=None):
    """
    Authenticate and call all fetch functions.
    Each is wrapped in try/except — failures return [] or {} so the build
    never aborts on a single query error.

    Auth priority:
      1. OAuth user credentials (client_id + client_secret + refresh_token)
      2. Service account JSON (credentials_file)
    """
    if client_id and client_secret and refresh_token:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
        )
    else:
        credentials, _ = google.auth.load_credentials_from_file(
            credentials_file,
            scopes=["https://www.googleapis.com/auth/adwords"],
        )
    # Use login_customer_id (manager) only when authenticating via service account.
    # With OAuth user credentials, authenticate directly against the client account.
    if client_id and client_secret and refresh_token:
        client = GoogleAdsClient(
            credentials=credentials,
            developer_token=developer_token,
        )
    else:
        client = GoogleAdsClient(
            credentials=credentials,
            developer_token=developer_token,
            login_customer_id=manager_id,
        )

    print("⏳  Google Ads: weekly totals...")
    try:
        weekly = fetch_weekly_google(client)
        print(f"    → {len(weekly)} complete weeks")
    except Exception as e:
        print(f"    ⚠️  weekly failed: {e}"); weekly = []

    print("⏳  Google Ads: campaigns...")
    try:
        camps = fetch_campaigns_google(client)
        print(f"    → {len(camps)} campaign-week rows")
    except Exception as e:
        print(f"    ⚠️  campaigns failed: {e}"); camps = []

    print("⏳  Google Ads: ads...")
    try:
        ads = fetch_ads_google(client)
        print(f"    → {len(ads)} ads")
    except Exception as e:
        print(f"    ⚠️  ads failed: {e}"); ads = []

    print("⏳  Google Ads: keywords...")
    try:
        kw, kw_weekly = fetch_keywords_google(client)
        print(f"    → {len(kw)} keywords, {len(kw_weekly)} keyword-week rows")
    except Exception as e:
        print(f"    ⚠️  keywords failed: {e}"); kw, kw_weekly = [], []

    print("⏳  Google Ads: geography...")
    try:
        geo = fetch_geo_google(client)
        print(f"    → {len(geo)} states")
    except Exception as e:
        print(f"    ⚠️  geography failed: {e}"); geo = {}

    return {
        "weekly":    weekly,
        "camps":     camps,
        "ads":       ads,
        "kw":        kw,
        "kw_weekly": kw_weekly,
        "geo":       geo,
    }

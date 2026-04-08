#!/usr/bin/env python3
"""
scripts/shared/msads_client.py
Pulls all Microsoft Advertising data needed for the PPC dashboard.

Dependencies: pip install bingads

Credentials (all from environment variables):
  MS_ADS_DEVELOPER_TOKEN  — developer token
  MS_ADS_CLIENT_ID        — Azure app client ID
  MS_ADS_CLIENT_SECRET    — Azure app client secret
  MS_ADS_CUSTOMER_ID      — 169512962
  MS_ADS_ACCOUNT_ID       — 176012710
  MS_ADS_REFRESH_TOKEN    — stored OAuth refresh token

Run scripts/msads_auth.py once locally to obtain the refresh token.
"""

import csv
import os
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta

from bingads import AuthorizationData, OAuthWebAuthCodeGrant, ServiceClient
from bingads.v13.reporting import ReportingDownloadParameters, ReportingServiceManager


# ─── DATE RANGE ───────────────────────────────────────────────────────────────

def _get_date_range(weeks=156):
    today       = date.today()
    this_monday = today - timedelta(days=today.weekday())
    last_sunday = this_monday - timedelta(days=1)
    start_dt    = this_monday - timedelta(weeks=weeks)
    return (
        start_dt,                         # date object
        last_sunday,                      # date object
        this_monday.strftime("%Y-%m-%d"), # string for exclusion check
    )


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _int(v):
    try:    return int(float(str(v).replace(",", "")))
    except: return 0

def _float(v, decimals=2):
    try:    return round(float(str(v).replace(",", "")), decimals)
    except: return 0.0

def _parse_week_start(time_period):
    """Parse Bing's 'M/D/YYYY - M/D/YYYY' time-period string → 'YYYY-MM-DD'."""
    if not time_period:
        return None
    try:
        start_str = str(time_period).split(" - ")[0].strip()
        return datetime.strptime(start_str, "%m/%d/%Y").strftime("%Y-%m-%d")
    except Exception:
        return None

def _strip_url(raw_url):
    """Strip domain from a display or final URL, return path only."""
    if not raw_url:
        return "/"
    for prefix in ("https://www.visme.co", "https://visme.co",
                   "http://www.visme.co", "http://visme.co",
                   "www.visme.co", "visme.co"):
        if raw_url.startswith(prefix):
            path = raw_url[len(prefix):]
            return path or "/"
    return raw_url

def _reporting_service(auth_data):
    """Create a Reporting ServiceClient (v13)."""
    return ServiceClient(
        service="ReportingService",
        version=13,
        authorization_data=auth_data,
        environment="production",
    )

def _make_report_time(svc, start_dt, end_dt):
    """Build a ReportTime SOAP object for a custom date range."""
    time = svc.factory.create("ReportTime")
    time.PredefinedTime = None

    cs = svc.factory.create("Date")
    cs.Day   = start_dt.day
    cs.Month = start_dt.month
    cs.Year  = start_dt.year
    time.CustomDateRangeStart = cs

    ce = svc.factory.create("Date")
    ce.Day   = end_dt.day
    ce.Month = end_dt.month
    ce.Year  = end_dt.year
    time.CustomDateRangeEnd = ce
    return time

def _account_scope(svc, account_id):
    scope = svc.factory.create("AccountReportScope")
    scope.AccountIds = {"long": [int(account_id)]}
    return scope

def _campaign_scope(svc, account_id):
    scope = svc.factory.create("AccountThroughCampaignReportScope")
    scope.AccountIds = {"long": [int(account_id)]}
    return scope

def _adgroup_scope(svc, account_id):
    scope = svc.factory.create("AccountThroughAdGroupReportScope")
    scope.AccountIds = {"long": [int(account_id)]}
    return scope

def _parse_report_csv(file_path):
    """
    Parse a Bing Ads CSV report (ExcludeReportHeader/Footer = True).
    Returns list of row dicts, stripping BOM, blank lines, and '©' footer lines.
    """
    with open(file_path, encoding="utf-8-sig") as f:
        content = f.read()

    lines = [l for l in content.splitlines()
             if l.strip() and not l.strip().startswith("©")]
    if not lines:
        return []

    reader = csv.DictReader(lines)
    rows = []
    for row in reader:
        if not row:
            continue
        first_val = next(iter(row.values()), "").strip()
        if first_val.lower() in ("total", ""):
            break
        rows.append({k.strip(): v.strip() for k, v in row.items() if k})
    return rows

def _download_rows(auth_data, report_request):
    """Submit a report, poll until complete, parse CSV, return list of dicts."""
    manager = ReportingServiceManager(
        authorization_data=auth_data,
        poll_interval_in_milliseconds=5000,
        environment="production",
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        params = ReportingDownloadParameters(
            report_request=report_request,
            result_file_directory=tmpdir,
            result_file_name="report.csv",
            overwrite_result_file=True,
            timeout_in_milliseconds=3_600_000,
        )
        result_file = manager.download_report(params)
        if result_file is None:
            return []
        return _parse_report_csv(result_file)


# ─── FUNCTION 1: fetch_weekly_msads ──────────────────────────────────────────

def fetch_weekly_msads(auth_data):
    """Weekly account-level totals, last 156 weeks. Sorted ascending."""
    start_dt, end_dt, this_monday = _get_date_range(156)
    svc = _reporting_service(auth_data)

    report = svc.factory.create("AccountPerformanceReportRequest")
    report.Aggregation          = "Weekly"
    report.Format               = "Csv"
    report.Language             = "English"
    report.ReportName           = "Weekly MS Ads Performance"
    report.ReturnOnlyCompleteData = False
    report.ExcludeReportHeader  = True
    report.ExcludeReportFooter  = True
    report.Scope                = _account_scope(svc, auth_data.account_id)
    report.Time                 = _make_report_time(svc, start_dt, end_dt)

    cols = svc.factory.create("ArrayOfAccountPerformanceReportColumn")
    cols.AccountPerformanceReportColumn = [
        "TimePeriod", "Spend", "Clicks", "Impressions", "Conversions",
    ]
    report.Columns = cols

    rows = _download_rows(auth_data, report)

    agg = defaultdict(lambda: {"spend": 0.0, "clicks": 0, "impressions": 0, "conversions": 0.0})
    for row in rows:
        week_start = _parse_week_start(row.get("Time period") or row.get("TimePeriod", ""))
        if not week_start or week_start >= this_monday:
            continue
        agg[week_start]["spend"]       += _float(row.get("Spend", 0))
        agg[week_start]["clicks"]      += _int(row.get("Clicks", 0))
        agg[week_start]["impressions"] += _int(row.get("Impressions", 0))
        agg[week_start]["conversions"] += _float(row.get("Conversions", 0))

    return [
        {
            "week_start":    w,
            "m_spend":       round(a["spend"], 2),
            "m_clicks":      a["clicks"],
            "m_impressions": a["impressions"],
            "m_conversions": round(a["conversions"], 2),
        }
        for w, a in sorted(agg.items())
    ]


# ─── FUNCTION 2: fetch_campaigns_msads ───────────────────────────────────────

def fetch_campaigns_msads(auth_data):
    """Per-campaign, per-week rows, last 156 weeks. Sorted ascending by week."""
    start_dt, end_dt, this_monday = _get_date_range(156)
    svc = _reporting_service(auth_data)

    report = svc.factory.create("CampaignPerformanceReportRequest")
    report.Aggregation          = "Weekly"
    report.Format               = "Csv"
    report.Language             = "English"
    report.ReportName           = "Weekly Campaign Performance"
    report.ReturnOnlyCompleteData = False
    report.ExcludeReportHeader  = True
    report.ExcludeReportFooter  = True
    report.Scope                = _campaign_scope(svc, auth_data.account_id)
    report.Time                 = _make_report_time(svc, start_dt, end_dt)

    cols = svc.factory.create("ArrayOfCampaignPerformanceReportColumn")
    cols.CampaignPerformanceReportColumn = [
        "TimePeriod", "CampaignName", "CampaignStatus", "CampaignType",
        "Spend", "Clicks", "Impressions", "Conversions",
    ]
    report.Columns = cols

    rows = _download_rows(auth_data, report)

    agg = {}
    for row in rows:
        week = _parse_week_start(row.get("Time period") or row.get("TimePeriod", ""))
        if not week or week >= this_monday:
            continue
        name = row.get("Campaign name") or row.get("CampaignName", "")
        key  = (week, name)
        if key not in agg:
            status_raw = row.get("Campaign status") or row.get("CampaignStatus", "")
            type_raw   = row.get("Campaign type")   or row.get("CampaignType", "")
            agg[key] = {
                "week":        week,
                "name":        name,
                "status":      status_raw,
                "type":        type_raw,
                "spend":       0.0,
                "clicks":      0,
                "impressions": 0,
                "conversions": 0.0,
            }
        agg[key]["spend"]       += _float(row.get("Spend", 0))
        agg[key]["clicks"]      += _int(row.get("Clicks", 0))
        agg[key]["impressions"] += _int(row.get("Impressions", 0))
        agg[key]["conversions"] += _float(row.get("Conversions", 0))

    result = []
    for key in sorted(agg):
        a = agg[key]
        a["spend"]       = round(a["spend"], 2)
        a["conversions"] = round(a["conversions"], 2)
        result.append(a)
    return result


# ─── FUNCTION 3: fetch_ads_msads ─────────────────────────────────────────────

def fetch_ads_msads(auth_data):
    """Ad performance aggregated over last 26 weeks. Sorted by spend descending."""
    start_dt, end_dt, _ = _get_date_range(26)
    svc = _reporting_service(auth_data)

    report = svc.factory.create("AdPerformanceReportRequest")
    report.Aggregation          = "Summary"
    report.Format               = "Csv"
    report.Language             = "English"
    report.ReportName           = "Ad Performance 26w"
    report.ReturnOnlyCompleteData = False
    report.ExcludeReportHeader  = True
    report.ExcludeReportFooter  = True
    report.Scope                = _adgroup_scope(svc, auth_data.account_id)
    report.Time                 = _make_report_time(svc, start_dt, end_dt)

    cols = svc.factory.create("ArrayOfAdPerformanceReportColumn")
    cols.AdPerformanceReportColumn = [
        "CampaignName", "AdGroupName", "TitlePart1", "TitlePart2", "TitlePart3",
        "AdDescription", "DisplayUrl", "AdStatus",
        "Clicks", "Impressions", "Conversions", "Spend",
    ]
    report.Columns = cols

    rows = _download_rows(auth_data, report)

    agg = {}
    for row in rows:
        campaign = row.get("Campaign name") or row.get("CampaignName", "")
        ad_group = row.get("Ad group")      or row.get("AdGroupName", "")
        h1       = row.get("Title part 1")  or row.get("TitlePart1", "")
        h2       = row.get("Title part 2")  or row.get("TitlePart2", "")
        h3       = row.get("Title part 3")  or row.get("TitlePart3", "")
        desc     = row.get("Ad description") or row.get("AdDescription", "")
        raw_url  = row.get("Display URL")   or row.get("DisplayUrl", "")
        url      = _strip_url(raw_url)
        status   = row.get("Ad status")     or row.get("AdStatus", "")

        key = (campaign, ad_group, h1, h2, h3, url)
        if key not in agg:
            agg[key] = {
                "campaign": campaign, "ad_group": ad_group,
                "headline1": h1, "headline2": h2, "headline3": h3,
                "description": desc, "url": url, "status": status,
                "clicks": 0, "impressions": 0, "conversions": 0.0, "cost": 0.0,
            }
        agg[key]["clicks"]      += _int(row.get("Clicks", 0))
        agg[key]["impressions"] += _int(row.get("Impressions", 0))
        agg[key]["conversions"] += _float(row.get("Conversions", 0))
        agg[key]["cost"]        += _float(row.get("Spend", 0))

    result = []
    for a in agg.values():
        a["cost"]        = round(a["cost"], 2)
        a["conversions"] = round(a["conversions"], 2)
        a["conv_rate"]   = round(a["conversions"] / a["clicks"],  4) if a["clicks"]      > 0 else 0.0
        a["cpa"]         = round(a["cost"]        / a["conversions"], 2) if a["conversions"] > 0 else 0.0
        result.append(a)
    return sorted(result, key=lambda x: x["cost"], reverse=True)


# ─── FUNCTION 4: fetch_keywords_msads ────────────────────────────────────────

def fetch_keywords_msads(auth_data):
    """Returns (kw_summary, kw_weekly) over the last 26 weeks."""
    start_dt, end_dt, this_monday = _get_date_range(26)
    svc = _reporting_service(auth_data)

    COMMON_COLS = [
        "Keyword", "MatchType", "CampaignName", "AdGroupName",
        "Spend", "Clicks", "Impressions", "Conversions",
    ]

    # — Summary: aggregate over 26 weeks —
    report_s = svc.factory.create("KeywordPerformanceReportRequest")
    report_s.Aggregation          = "Summary"
    report_s.Format               = "Csv"
    report_s.Language             = "English"
    report_s.ReportName           = "Keyword Summary 26w"
    report_s.ReturnOnlyCompleteData = False
    report_s.ExcludeReportHeader  = True
    report_s.ExcludeReportFooter  = True
    report_s.Scope                = _adgroup_scope(svc, auth_data.account_id)
    report_s.Time                 = _make_report_time(svc, start_dt, end_dt)
    cols_s = svc.factory.create("ArrayOfKeywordPerformanceReportColumn")
    cols_s.KeywordPerformanceReportColumn = COMMON_COLS
    report_s.Columns              = cols_s

    rows_s = _download_rows(auth_data, report_s)

    agg_s = {}
    for row in rows_s:
        kw   = row.get("Keyword", "")
        mt   = row.get("Match type") or row.get("MatchType", "")
        camp = row.get("Campaign name") or row.get("CampaignName", "")
        ag   = row.get("Ad group")      or row.get("AdGroupName", "")
        key  = (kw, mt, camp, ag)
        if key not in agg_s:
            agg_s[key] = {"keyword": kw, "match_type": mt, "campaign": camp,
                          "ad_group": ag, "spend": 0.0, "clicks": 0,
                          "impressions": 0, "conversions": 0.0}
        agg_s[key]["spend"]       += _float(row.get("Spend", 0))
        agg_s[key]["clicks"]      += _int(row.get("Clicks", 0))
        agg_s[key]["impressions"] += _int(row.get("Impressions", 0))
        agg_s[key]["conversions"] += _float(row.get("Conversions", 0))

    kw_summary = []
    for a in agg_s.values():
        a["spend"] = round(a["spend"], 2); a["conversions"] = round(a["conversions"], 2)
        a["ctr"]       = round(a["clicks"] / a["impressions"], 4) if a["impressions"] > 0 else 0.0
        a["cpa"]       = round(a["spend"]  / a["conversions"],  2) if a["conversions"] > 0 else 0.0
        a["conv_rate"] = round(a["conversions"] / a["clicks"],  4) if a["clicks"]      > 0 else 0.0
        kw_summary.append(a)
    kw_summary.sort(key=lambda x: x["spend"], reverse=True)

    # — Weekly: 26 weeks, one row per keyword × week —
    report_w = svc.factory.create("KeywordPerformanceReportRequest")
    report_w.Aggregation          = "Weekly"
    report_w.Format               = "Csv"
    report_w.Language             = "English"
    report_w.ReportName           = "Keyword Weekly 26w"
    report_w.ReturnOnlyCompleteData = False
    report_w.ExcludeReportHeader  = True
    report_w.ExcludeReportFooter  = True
    report_w.Scope                = _adgroup_scope(svc, auth_data.account_id)
    report_w.Time                 = _make_report_time(svc, start_dt, end_dt)
    cols_w = svc.factory.create("ArrayOfKeywordPerformanceReportColumn")
    cols_w.KeywordPerformanceReportColumn = ["TimePeriod"] + COMMON_COLS
    report_w.Columns              = cols_w

    rows_w = _download_rows(auth_data, report_w)

    agg_w = {}
    for row in rows_w:
        week = _parse_week_start(row.get("Time period") or row.get("TimePeriod", ""))
        if not week or week >= this_monday:
            continue
        kw   = row.get("Keyword", "")
        mt   = row.get("Match type") or row.get("MatchType", "")
        camp = row.get("Campaign name") or row.get("CampaignName", "")
        ag   = row.get("Ad group")      or row.get("AdGroupName", "")
        key  = (week, kw, mt, camp, ag)
        if key not in agg_w:
            agg_w[key] = {"week": week, "keyword": kw, "match_type": mt,
                          "campaign": camp, "ad_group": ag, "spend": 0.0,
                          "clicks": 0, "impressions": 0, "conversions": 0.0}
        agg_w[key]["spend"]       += _float(row.get("Spend", 0))
        agg_w[key]["clicks"]      += _int(row.get("Clicks", 0))
        agg_w[key]["impressions"] += _int(row.get("Impressions", 0))
        agg_w[key]["conversions"] += _float(row.get("Conversions", 0))

    kw_weekly = []
    for a in sorted(agg_w.values(), key=lambda x: (x["week"], x["keyword"])):
        a["spend"] = round(a["spend"], 2); a["conversions"] = round(a["conversions"], 2)
        a["ctr"] = round(a["clicks"] / a["impressions"], 4) if a["impressions"] > 0 else 0.0
        kw_weekly.append(a)

    return kw_summary, kw_weekly


# ─── FUNCTION 5: fetch_geo_msads ─────────────────────────────────────────────

def fetch_geo_msads(auth_data):
    """
    US state performance aggregated over last 26 weeks.
    Returns dict keyed by state name.
    """
    start_dt, end_dt, _ = _get_date_range(26)
    svc = _reporting_service(auth_data)

    report = svc.factory.create("GeographicPerformanceReportRequest")
    report.Aggregation          = "Summary"
    report.Format               = "Csv"
    report.Language             = "English"
    report.ReportName           = "Geo Performance 26w"
    report.ReturnOnlyCompleteData = False
    report.ExcludeReportHeader  = True
    report.ExcludeReportFooter  = True
    report.Scope                = _adgroup_scope(svc, auth_data.account_id)
    report.Time                 = _make_report_time(svc, start_dt, end_dt)

    cols = svc.factory.create("ArrayOfGeographicPerformanceReportColumn")
    cols.GeographicPerformanceReportColumn = [
        "Country", "State", "Spend", "Clicks", "Conversions",
    ]
    report.Columns = cols

    rows = _download_rows(auth_data, report)

    agg = defaultdict(lambda: {"spend": 0.0, "clicks": 0, "conversions": 0.0})
    for row in rows:
        country = row.get("Country/Region") or row.get("Country", "")
        if country.strip().lower() != "united states":
            continue
        state = (row.get("State") or row.get("Province") or "").strip()
        if not state or state.lower() in ("unknown", ""):
            continue
        agg[state]["spend"]       += _float(row.get("Spend", 0))
        agg[state]["clicks"]      += _int(row.get("Clicks", 0))
        agg[state]["conversions"] += _float(row.get("Conversions", 0))

    result = {}
    for state, a in agg.items():
        spend = round(a["spend"], 2)
        convs = round(a["conversions"], 2)
        clks  = a["clicks"]
        result[state] = {
            "ms_spend":     spend,
            "ms_clicks":    clks,
            "ms_conversions": convs,
            "ms_cpa":       round(spend / convs, 2) if convs > 0 else 0.0,
            "ms_conv_rate": round(convs / clks,  4) if clks  > 0 else 0.0,
        }
    return result


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def fetch_all_msads(developer_token, client_id, client_secret,
                    refresh_token, customer_id, account_id):
    """
    Authenticate and call all fetch functions.
    Each is wrapped in try/except — failures return [] or {} so the build
    never aborts on a single query error.
    """
    if not refresh_token:
        raise RuntimeError(
            "MS_ADS_REFRESH_TOKEN is not set. "
            "Run `python scripts/msads_auth.py` locally to obtain a refresh token, "
            "then save it as the MS_ADS_REFRESH_TOKEN GitHub secret."
        )

    authentication = OAuthWebAuthCodeGrant(
        client_id=client_id,
        client_secret=client_secret,
        redirection_uri="https://login.microsoftonline.com/common/oauth2/nativeClient",
    )
    try:
        authentication.request_oauth_tokens_by_refresh_token(refresh_token)
    except Exception as e:
        raise RuntimeError(
            f"Microsoft Ads token refresh failed: {e}\n"
            "The refresh token may be expired. "
            "Run `python scripts/msads_auth.py` to obtain a new one."
        ) from e

    auth_data = AuthorizationData(
        account_id=int(account_id),
        customer_id=int(customer_id),
        developer_token=developer_token,
        authentication=authentication,
    )

    print("⏳  Microsoft Ads: weekly totals...")
    try:
        weekly = fetch_weekly_msads(auth_data)
        print(f"    → {len(weekly)} complete weeks")
    except Exception as e:
        print(f"    ⚠️  weekly failed: {e}"); weekly = []

    print("⏳  Microsoft Ads: campaigns...")
    try:
        camps = fetch_campaigns_msads(auth_data)
        print(f"    → {len(camps)} campaign-week rows")
    except Exception as e:
        print(f"    ⚠️  campaigns failed: {e}"); camps = []

    print("⏳  Microsoft Ads: ads...")
    try:
        ads = fetch_ads_msads(auth_data)
        print(f"    → {len(ads)} ads")
    except Exception as e:
        print(f"    ⚠️  ads failed: {e}"); ads = []

    print("⏳  Microsoft Ads: keywords...")
    try:
        kw, kw_weekly = fetch_keywords_msads(auth_data)
        print(f"    → {len(kw)} keywords, {len(kw_weekly)} keyword-week rows")
    except Exception as e:
        print(f"    ⚠️  keywords failed: {e}"); kw, kw_weekly = [], []

    print("⏳  Microsoft Ads: geography...")
    try:
        geo = fetch_geo_msads(auth_data)
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

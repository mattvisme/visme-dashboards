"""
scripts/shared/sheets_client.py
Shared Google Sheets reader for HubSpot, Amplitude, PPC, and GSC data.
"""

import json
import os
import re
import socket
import sys
import tempfile
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

from scripts.shared.title_classifier import classify_title, OTHER_UNCLASSIFIED

SCOPES    = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SCOPES_RW = ["https://www.googleapis.com/auth/spreadsheets"]

HUBSPOT_SHEET_ID   = os.environ.get("HUBSPOT_SHEET_ID",
                                     "1TsDySDrmgSQEUjunQg77twgUS1fGgZIC71IbX-bAz1s")
AMPLITUDE_SHEET_ID = os.environ.get("AMPLITUDE_SHEET_ID",
                                     "11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw")
PPC_SHEET_ID       = os.environ.get("PPC_SHEET_ID",
                                     "11YiWr1aHhwBto9JrgwnSGJLtyq1KEfJvs5ZRbkoWKho")
GSC_SHEET_ID       = os.environ.get("GSC_SHEET_ID", "")
CHANNEL_PERF_SHEET_ID = os.environ.get("CHANNEL_PERF_SHEET_ID",
                                        "1F6h9jAVy7SEHiF1jS_HkFZ6Htu5fYJ-Q8yQxe0iJvCI")

# Week 1's Monday, per the "Weekly Conversion & Signups channels" sheet's own
# tab "Week 1 - Dec 29 - Jan 4". Verified: Dec 29, 2025 IS a Monday, and
# Week 1's Monday + 32 weeks lands on Aug 10, 2026 — which IS a Monday and
# matches the sheet's Week 33 tab "Aug 10 - 16" exactly (checked directly in
# the sheet on 2026-08-21). Every week tab's Monday is computed from this
# single verified anchor, not re-parsed from each tab's free-text label,
# since month abbreviations in those labels are inconsistent (e.g. "Aug 3-9"
# vs. "June 29 - July 5").
CHANNEL_PERF_WEEK1_MONDAY = date(2025, 12, 29)


def _execute(request, retries: int = 3):
    """
    Execute a Google API request with retry on transient network errors.
    Covers socket timeouts and connection resets that occur in CI runners
    (GitHub Actions) where SSL read timeouts are common on cold starts.
    googleapiclient's built-in num_retries only handles 5xx HTTP errors,
    not socket-level TimeoutError / ConnectionError, so we wrap it here.
    """
    for attempt in range(retries):
        try:
            return request.execute(num_retries=2)
        except (TimeoutError, ConnectionError, socket.timeout, OSError) as exc:
            if attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"  ⚠️  Sheets API network error ({exc}). Retrying in {wait}s…")
                time.sleep(wait)
            else:
                raise


def _resolve_credentials_file(credentials_file=None) -> str:
    """Resolve the service account credentials file path."""
    creds_json = os.environ.get("GA4_CREDENTIALS_JSON")
    if creds_json:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(creds_json)
        tmp.close()
        return tmp.name
    if credentials_file:
        return credentials_file
    return os.environ.get(
        "GA4_CREDENTIALS_FILE",
        os.path.join(os.path.expanduser("~"), "Downloads",
                     "visme-marketing-491309-8316da126688.json")
    )


def _get_sheets_service(credentials_file=None):
    """Build an authenticated read-only Google Sheets service."""
    path = _resolve_credentials_file(credentials_file)
    creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()


def _get_sheets_service_rw(credentials_file=None):
    """Build an authenticated read-write Google Sheets service."""
    path = _resolve_credentials_file(credentials_file)
    creds = Credentials.from_service_account_file(path, scopes=SCOPES_RW)
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()


def _parse_float(v):
    if v is None or str(v).strip() == "":
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return 0.0


def _fmt_label(date_str: str) -> str:
    """'2024-03-11' -> \"Mar 11 '24\" """
    d = datetime.strptime(date_str, "%Y-%m-%d")
    if sys.platform == "win32":
        return f"{d.strftime('%b')} {d.day} '{d.strftime('%y')}"
    return d.strftime("%b %-d '%y")


def fetch_hubspot_data(sheet_id=None, credentials_file=None) -> dict:
    """
    Read HubSpot Weekly Summary and Weekly Channels tabs from Google Sheets.

    Returns:
        {
          weeks: [date_str, ...],
          weekLabels: [label, ...],
          summary: {date_str: {leads, mqls, deals, pipeline, revenue}},
          channels: {date_str: {channel: {leads, deals, pipeline, revenue}}},
          lastDate: date_str
        }
    """
    if sheet_id is None:
        sheet_id = HUBSPOT_SHEET_ID

    sheets = _get_sheets_service(credentials_file)

    # Weekly Summary tab
    print("  Pulling HubSpot 'Weekly Summary'…")
    result = _execute(sheets.values().get(spreadsheetId=sheet_id, range="Weekly Summary!A2:G"))
    rows = result.get("values", [])
    summary = {}
    skipped_s = 0
    for row in rows:
        if not row or len(row) < 1:
            continue
        try:
            date_str = str(row[0]).strip()
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            skipped_s += 1
            continue
        summary[date_str] = {
            "leads":          _parse_float(row[1] if len(row) > 1 else None),
            "mqls":           _parse_float(row[2] if len(row) > 2 else None),
            "deals":          _parse_float(row[3] if len(row) > 3 else None),
            "pipeline":       _parse_float(row[4] if len(row) > 4 else None),
            "revenue":        _parse_float(row[5] if len(row) > 5 else None),
            "closedWonCount": int(float(row[6])) if len(row) > 6 and str(row[6]).strip() not in ("", "None") else 0,
        }
    print(f"    {len(summary)} valid summary rows  ({skipped_s} skipped)")

    # Weekly Channels tab
    print("  Pulling HubSpot 'Weekly Channels'…")
    result2 = _execute(sheets.values().get(spreadsheetId=sheet_id, range="Weekly Channels!A2:F"))
    rows2 = result2.get("values", [])
    channels = {}
    skipped_c = 0
    for row in rows2:
        if not row or len(row) < 2:
            continue
        try:
            date_str = str(row[0]).strip()
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            skipped_c += 1
            continue
        channel = str(row[1]).strip()
        if date_str not in channels:
            channels[date_str] = {}
        channels[date_str][channel] = {
            "leads":    _parse_float(row[2] if len(row) > 2 else None),
            "deals":    _parse_float(row[3] if len(row) > 3 else None),
            "pipeline": _parse_float(row[4] if len(row) > 4 else None),
            "revenue":  _parse_float(row[5] if len(row) > 5 else None),
        }
    print(f"    {len(channels)} unique channel weeks  ({skipped_c} skipped)")

    this_monday_str = (date.today() - timedelta(days=date.today().weekday())).strftime("%Y-%m-%d")
    all_dates = [d for d in sorted(set(list(summary.keys()) + list(channels.keys())))
                 if d < this_monday_str]
    last_monday_dt = datetime.strptime(all_dates[-1], "%Y-%m-%d").date() if all_dates else date.today()
    last_date = (last_monday_dt + timedelta(days=6)).strftime("%Y-%m-%d")

    payload = {
        "weeks":      all_dates,
        "weekLabels": [_fmt_label((datetime.strptime(d, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")) for d in all_dates],
        "summary":    summary,
        "channels":   channels,
        "lastDate":   last_date,
    }
    print(f"  HS payload ready — {len(all_dates)} weeks, lastDate={last_date}")
    return payload


def fetch_amplitude_data(sheet_id=None, credentials_file=None) -> dict:
    """
    Read Amplitude data from Google Sheets (Full 2025 weekly + Weekly tabs).

    Returns:
        {
          weeks: [date_str, ...],
          weekLabels: [label, ...],
          signups: {date_str: int},
          upgrades: {date_str: int},
          activations: {date_str: int},
          cr: {date_str: float|None},
          lastDate: date_str
        }
    """
    if sheet_id is None:
        sheet_id = AMPLITUDE_SHEET_ID

    sheets = _get_sheets_service(credentials_file)

    def pull_tab(tab_name):
        print(f"  Pulling Amplitude '{tab_name}'…")
        result = _execute(sheets.values().get(
            spreadsheetId=sheet_id,
            range=f"'{tab_name}'!A2:E"
        ))
        rows = result.get("values", [])
        data = {}
        skipped = 0
        for row in rows:
            if not row or not row[0]:
                continue
            date_str = str(row[0]).strip()
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                skipped += 1
                continue

            def safe_int(v):
                try:
                    return int(str(v).replace(",", "").strip())
                except Exception:
                    return 0

            def safe_float(v):
                try:
                    return float(str(v).replace("%", "").strip())
                except Exception:
                    return None

            data[date_str] = {
                "signups":     safe_int(row[1])   if len(row) > 1 else 0,
                "upgrades":    safe_int(row[2])   if len(row) > 2 else 0,
                "activations": safe_int(row[3])   if len(row) > 3 else 0,
                "cr":          safe_float(row[4]) if len(row) > 4 else None,
            }
        print(f"    {len(data)} valid rows  ({skipped} skipped)")
        return data

    data_full   = pull_tab("Full 2025 weekly")
    data_weekly = pull_tab("Weekly")

    # Merge: Full first, Weekly overrides on overlap
    merged = {**data_full, **data_weekly}
    this_monday_str = (date.today() - timedelta(days=date.today().weekday())).strftime("%Y-%m-%d")
    sorted_dates = [d for d in sorted(merged.keys()) if d < this_monday_str]
    print(f"  Amplitude merged: {len(sorted_dates)} unique weeks "
          f"({sorted_dates[0] if sorted_dates else '-'} to {sorted_dates[-1] if sorted_dates else '-'})")

    last_monday_dt = datetime.strptime(sorted_dates[-1], "%Y-%m-%d").date() if sorted_dates else date.today()
    last_date = (last_monday_dt + timedelta(days=6)).strftime("%Y-%m-%d")

    payload = {
        "weeks":       sorted_dates,
        "weekLabels":  [_fmt_label((datetime.strptime(d, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")) for d in sorted_dates],
        "signups":     {d: merged[d]["signups"]     for d in sorted_dates},
        "upgrades":    {d: merged[d]["upgrades"]    for d in sorted_dates},
        "activations": {d: merged[d]["activations"] for d in sorted_dates},
        "cr":          {d: merged[d]["cr"]          for d in sorted_dates},
        "lastDate":    last_date,
    }
    return payload


def fetch_ppc_data(sheet_id=None) -> dict:
    """
    Read raw_campaign_daily and raw_conv_actions_daily from the PPC Google Sheet
    and aggregate into weekly metrics.

    Tab schemas:
        raw_campaign_daily (A:H):
            date, campaign_id, campaign_name, cost, impressions, clicks,
            conversions, search_impr_share
        raw_conv_actions_daily (A:F):
            date, campaign_id, campaign_name, conversion_action_name,
            conversions, all_conversions_value

    Revenue excludes rows where conversion_action_name == "Purchase-upload".

    Returns:
        {
            "generatedAt": "YYYY-MM-DD",
            "weeks":   ["YYYY-MM-DD", ...],   # Monday boundaries, oldest-first
            "spend":   {"YYYY-MM-DD": float},
            "clicks":  {"YYYY-MM-DD": int},
            "ctr":     {"YYYY-MM-DD": float},  # clicks/impressions, 0 if impr==0
            "convs":   {"YYYY-MM-DD": float},
            "cpc":     {"YYYY-MM-DD": float},  # spend/convs, 0 if convs==0
            "revenue": {"YYYY-MM-DD": float},
        }
        Note: "signups" is NOT included — merged in by build_ppc.py.
    """
    if sheet_id is None:
        sheet_id = PPC_SHEET_ID

    sheets = _get_sheets_service()

    def _parse_num(v, cast=float):
        if v is None or str(v).strip() == "":
            return cast(0)
        try:
            return cast(str(v).replace(",", "").replace("$", "").strip())
        except (ValueError, TypeError):
            return cast(0)

    def _get_monday(d: date) -> str:
        """Return YYYY-MM-DD string for the Monday of the week containing d."""
        monday = d - timedelta(days=d.weekday())
        return monday.strftime("%Y-%m-%d")

    # ── raw_campaign_daily ────────────────────────────────────────────────────
    print("  Pulling PPC 'raw_campaign_daily'…")
    result = _execute(sheets.values().get(
        spreadsheetId=sheet_id, range="raw_campaign_daily!A:H"
    ))
    campaign_rows = result.get("values", [])
    if campaign_rows:
        campaign_rows = campaign_rows[1:]   # skip header row

    print(f"  PPC campaign rows: {len(campaign_rows)}")

    # Weekly accumulators
    w_spend       = {}
    w_clicks      = {}
    w_impressions = {}
    w_convs       = {}

    for row in campaign_rows:
        if not row or not row[0]:
            continue
        date_str = str(row[0]).strip()
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        week = _get_monday(d)
        cost        = _parse_num(row[3] if len(row) > 3 else None, float)
        impressions = _parse_num(row[4] if len(row) > 4 else None, float)
        clicks      = _parse_num(row[5] if len(row) > 5 else None, float)
        convs       = _parse_num(row[6] if len(row) > 6 else None, float)

        w_spend[week]       = w_spend.get(week, 0.0)       + cost
        w_impressions[week] = w_impressions.get(week, 0.0) + impressions
        w_clicks[week]      = w_clicks.get(week, 0.0)      + clicks
        w_convs[week]       = w_convs.get(week, 0.0)       + convs

    # ── raw_conv_actions_daily ────────────────────────────────────────────────
    print("  Pulling PPC 'raw_conv_actions_daily'…")
    result2 = _execute(sheets.values().get(
        spreadsheetId=sheet_id, range="raw_conv_actions_daily!A:F"
    ))
    conv_rows = result2.get("values", [])
    if conv_rows:
        conv_rows = conv_rows[1:]   # skip header row

    print(f"  PPC conv action rows: {len(conv_rows)}")

    EXCLUDE_ACTION = "Purchase-upload"
    w_revenue = {}

    for row in conv_rows:
        if not row or not row[0]:
            continue
        date_str = str(row[0]).strip()
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        action_name = str(row[3]).strip() if len(row) > 3 else ""
        if action_name == EXCLUDE_ACTION:
            continue
        value = _parse_num(row[5] if len(row) > 5 else None, float)
        week  = _get_monday(d)
        w_revenue[week] = w_revenue.get(week, 0.0) + value

    # ── Assemble weeks list (oldest-first, complete weeks only) ──────────────
    this_monday = (date.today() - timedelta(days=date.today().weekday())).strftime("%Y-%m-%d")
    all_weeks = [w for w in sorted(w_spend.keys()) if w < this_monday]
    print(f"  PPC weeks found: {len(all_weeks)} (excluded current incomplete week {this_monday})")

    # generatedAt = last Sunday of the most recent complete week (Monday + 6 days),
    # so "Data as of" shows the week-end date consistent with other dashboards.
    last_monday_dt = datetime.strptime(all_weeks[-1], "%Y-%m-%d").date() if all_weeks else date.today()
    last_data_date = (last_monday_dt + timedelta(days=6)).strftime("%Y-%m-%d")

    payload = {
        "generatedAt": last_data_date,
        "weeks":  all_weeks,
        "spend":  {w: round(w_spend.get(w, 0.0), 2)   for w in all_weeks},
        "clicks": {w: int(w_clicks.get(w, 0))          for w in all_weeks},
        "ctr":    {
            w: round(w_clicks.get(w, 0) / w_impressions[w], 4)
            if w_impressions.get(w, 0) > 0 else 0
            for w in all_weeks
        },
        "convs":   {w: round(w_convs.get(w, 0.0), 2)   for w in all_weeks},
        "cpc":     {
            w: round(w_spend.get(w, 0.0) / w_convs[w], 2)
            if w_convs.get(w, 0) > 0 else 0
            for w in all_weeks
        },
        "revenue": {w: round(w_revenue.get(w, 0.0), 2) for w in all_weeks},
    }
    return payload


def fetch_gsc_sheet_data(sheet_id=None, credentials_file=None) -> dict:
    """
    Read GSC data from a Google Sheet populated by the GSC Apps Script exporter.

    Tab schemas (all have a header row):
        gsc_weekly (A:E):
            week | clicks | impressions | ctr | position
        gsc_queries (A:G):
            window | query | clicks | clicks_py | impressions | ctr | position
        gsc_pages (A:G):
            window | url | clicks | clicks_py | impressions | ctr | position
        gsc_countries (A:G):
            window | country | clicks | clicks_py | impressions | ctr | position

    Returns the D object expected by gsc/index.html:
        {
          generatedAt, startDate, endDate,
          weeks, wClicks, wImpressions, wCtr, wPosition,
          positionDist, ctrByPos,
          queryWindows, pageWindows, countryWindows
        }
    """
    if sheet_id is None:
        sheet_id = GSC_SHEET_ID

    sheets = _get_sheets_service(credentials_file)

    # ── gsc_weekly ────────────────────────────────────────────────────────────
    print("  Pulling GSC 'gsc_weekly'…")
    result = _execute(sheets.values().get(spreadsheetId=sheet_id, range="gsc_weekly!A2:E"))
    rows = result.get("values", [])

    w_clicks = {}
    w_impr   = {}
    w_ctr    = {}
    w_pos    = {}
    skipped  = 0

    for row in rows:
        if not row or not row[0]:
            continue
        week = str(row[0]).strip()
        try:
            datetime.strptime(week, "%Y-%m-%d")
        except ValueError:
            skipped += 1
            continue
        w_clicks[week] = int(_parse_float(row[1] if len(row) > 1 else None))
        w_impr[week]   = int(_parse_float(row[2] if len(row) > 2 else None))
        ctr_val        = _parse_float(row[3] if len(row) > 3 else None)
        w_ctr[week]    = round(ctr_val, 6)
        pos_val        = _parse_float(row[4] if len(row) > 4 else None)
        w_pos[week]    = round(pos_val, 3) if pos_val > 0 else None

    all_weeks  = sorted(w_clicks.keys())

    # Exclude weeks whose Sunday end-date hasn't fully settled in GSC yet.
    # GSC has a ~3-day processing lag, so the most recently written week row
    # often contains only 1 day of data. Drop any week whose Sunday is within
    # 3 days of today so partial data never appears in the dashboard.
    from datetime import date, timedelta
    _gsc_cutoff = date.today() - timedelta(days=3)
    all_weeks = [w for w in all_weeks
                 if date.fromisoformat(w) + timedelta(days=6) <= _gsc_cutoff]

    start_date = all_weeks[0]  if all_weeks else ""
    # end_date is the Sunday (week-end) of the last complete week
    end_date = (date.fromisoformat(all_weeks[-1]) + timedelta(days=6)).isoformat() if all_weeks else ""
    print(f"    {len(all_weeks)} weeks  ({skipped} skipped, partial weeks dropped)  endDate={end_date}")

    # ── dimension windows (queries / pages / countries) ───────────────────────
    def read_window_tab(tab_name, key_field):
        print(f"  Pulling GSC '{tab_name}'…")
        res = _execute(sheets.values().get(spreadsheetId=sheet_id,
                                          range=f"{tab_name}!A2:G"))
        tab_rows = res.get("values", [])
        windows = {}
        for row in tab_rows:
            if not row or len(row) < 2:
                continue
            win = str(row[0]).strip()
            if not win:
                continue
            key = str(row[1]).strip()
            item = {
                key_field:   key,
                "clicks":    int(_parse_float(row[2] if len(row) > 2 else None)),
                "clicks_py": int(_parse_float(row[3] if len(row) > 3 else None)),
                "impr":      int(_parse_float(row[4] if len(row) > 4 else None)),
                "ctr":       round(_parse_float(row[5] if len(row) > 5 else None), 6),
                "pos":       round(_parse_float(row[6] if len(row) > 6 else None), 3),
            }
            if win not in windows:
                windows[win] = {"cur": []}
            windows[win]["cur"].append(item)
        total = sum(len(v["cur"]) for v in windows.values())
        print(f"    {total} rows across {len(windows)} windows")
        return windows

    query_windows   = read_window_tab("gsc_queries",   "q")
    page_windows    = read_window_tab("gsc_pages",     "url")
    country_windows = read_window_tab("gsc_countries", "country")

    # Compute CTR by position bucket from the widest available query window.
    # Queries are grouped by their average position, then weighted CTR
    # (clicks / impressions) is calculated per bucket. Stored as a percentage
    # number (e.g. 3.45 means 3.45%) to match the dashboard's toFixed(2)+'%'.
    def _compute_ctr_by_pos(q_windows):
        for win in ["52", "26", "13", "8"]:
            if win in q_windows and q_windows[win].get("cur"):
                queries = q_windows[win]["cur"]
                break
        else:
            return {}
        buckets = {k: {"clicks": 0, "impr": 0}
                   for k in ("top3", "top10", "top20", "other")}
        for q in queries:
            pos = q.get("pos") or 0
            if pos <= 3.5:
                b = "top3"
            elif pos <= 10.5:
                b = "top10"
            elif pos <= 20.5:
                b = "top20"
            else:
                b = "other"
            buckets[b]["clicks"] += q.get("clicks", 0)
            buckets[b]["impr"]   += q.get("impr", 0)
        # Store as decimal (0–1) to match wCtr — fmtCtr(v) = (v*100).toFixed(2)+'%'
        return {
            b: round(d["clicks"] / d["impr"], 6) if d["impr"] > 0 else 0.0
            for b, d in buckets.items()
        }

    ctr_by_pos = _compute_ctr_by_pos(query_windows)
    print(f"  ctrByPos computed: { {k: f'{v:.2f}%' for k, v in ctr_by_pos.items()} }")

    payload = {
        "generatedAt":    end_date,
        "startDate":      start_date,
        "endDate":        end_date,
        "weeks":          all_weeks,
        "wClicks":        w_clicks,
        "wImpressions":   w_impr,
        "wCtr":           w_ctr,
        "wPosition":      w_pos,
        "positionDist":   {},
        "ctrByPos":       ctr_by_pos,
        "queryWindows":   query_windows,
        "pageWindows":    page_windows,
        "countryWindows": country_windows,
    }
    print(f"  GSC sheet payload ready — {len(all_weeks)} weeks, endDate={end_date}")
    return payload


def fetch_google_ads_from_sheet(sheet_id=None, credentials_file=None) -> dict:
    """
    Read raw_campaign_daily from the PPC Google Sheet and return the same
    structure that google_ads_client.fetch_all_google_ads() would produce.

    Tab schema — raw_campaign_daily (A:H):
        date, campaign_id, campaign_name, cost, impressions, clicks,
        conversions, search_impr_share

    Campaign type is inferred from the name prefix:
        GS_ → Search  |  GV_ → Video  |  GD_ → Display
        PMAX_ / PM_ → PMax  |  otherwise → Other

    Returns:
        {
          "weekly":    [{week_start, week_end, label, g_spend, g_clicks,
                         g_impressions, g_conversions}],
          "camps":     [{name, type, spend, clicks, impressions, conversions}],
          "ads":       [],
          "kw":        [],
          "kw_weekly": [],
          "geo":       {},
          "budgets":   {},
          "build_date": "YYYY-MM-DD",
        }
    """
    if sheet_id is None:
        sheet_id = PPC_SHEET_ID

    sheets = _get_sheets_service(credentials_file)

    def _n(v, cast=float):
        if v is None or str(v).strip() == "":
            return cast(0)
        try:
            return cast(str(v).replace(",", "").replace("$", "").strip())
        except (ValueError, TypeError):
            return cast(0)

    def _get_monday(d: date) -> str:
        return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")

    def _infer_type(name: str) -> str:
        n = name.upper()
        # Check specific patterns before generic prefixes
        if "PMAX" in n or n.startswith("PM_"): return "Performance max"
        if "DEMAND_GEN" in n or "DEMAND GEN" in n: return "Demand gen"
        if n.startswith("GS_"):    return "Search"
        if n.startswith("GV_"):    return "Video"
        if n.startswith("GD_"):    return "Display"
        return "Other"

    print("Google Ads (sheet): reading raw_campaign_daily...")
    result = _execute(sheets.values().get(
        spreadsheetId=sheet_id, range="raw_campaign_daily!A:H"
    ))
    rows = result.get("values", [])[1:]   # skip header

    today       = date.today()
    this_monday = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")

    # Weekly totals (for WEEKLY array)
    w_spend = {}; w_impr = {}; w_clicks = {}; w_convs = {}

    # Per-week per-campaign rows (for CAMPS_G — JS filters by week window)
    wc_data = {}  # key: (week, camp) -> metrics dict

    for row in rows:
        if not row or not row[0]:
            continue
        try:
            d = datetime.strptime(str(row[0]).strip(), "%Y-%m-%d").date()
        except ValueError:
            continue
        week = _get_monday(d)
        camp = str(row[2]).strip() if len(row) > 2 else "Unknown"
        cost  = _n(row[3] if len(row) > 3 else None)
        impr  = _n(row[4] if len(row) > 4 else None)
        clk   = _n(row[5] if len(row) > 5 else None)
        conv  = _n(row[6] if len(row) > 6 else None)

        w_spend[week]  = w_spend.get(week, 0.0)  + cost
        w_impr[week]   = w_impr.get(week, 0.0)   + impr
        w_clicks[week] = w_clicks.get(week, 0.0) + clk
        w_convs[week]  = w_convs.get(week, 0.0)  + conv

        key = (week, camp)
        if key not in wc_data:
            wc_data[key] = {
                "week":        week,
                "name":        camp,
                "type":        _infer_type(camp),
                "status":      "Active",
                "spend":       0.0,
                "clicks":      0,
                "impressions": 0,
                "conversions": 0.0,
            }
        wc_data[key]["spend"]       += cost
        wc_data[key]["clicks"]      += int(clk)
        wc_data[key]["impressions"] += int(impr)
        wc_data[key]["conversions"] += conv

    all_weeks = [w for w in sorted(w_spend) if w < this_monday]
    print(f"  -> {len(all_weeks)} complete weeks  "
          f"({all_weeks[0] if all_weeks else '-'} to {all_weeks[-1] if all_weeks else '-'})")

    weekly = []
    for ws in all_weeks:
        we = (datetime.strptime(ws, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")
        weekly.append({
            "week_start":    ws,
            "week_end":      we,
            "label":         _fmt_label(we),
            "g_spend":       round(w_spend.get(ws, 0.0), 2),
            "g_clicks":      int(w_clicks.get(ws, 0)),
            "g_impressions": int(w_impr.get(ws, 0)),
            "g_conversions": round(w_convs.get(ws, 0.0), 2),
        })

    camps = sorted(
        [
            {
                "week":        r["week"],
                "name":        r["name"],
                "type":        r["type"],
                "status":      r["status"],
                "spend":       round(r["spend"], 2),
                "clicks":      r["clicks"],
                "impressions": r["impressions"],
                "conversions": round(r["conversions"], 2),
            }
            for r in wc_data.values()
        ],
        key=lambda r: (r["week"], r["name"]),
    )
    print(f"  -> {len(camps)} campaign-week rows ({len(set(r['name'] for r in camps))} campaigns)")

    return {
        "weekly":    weekly,
        "camps":     camps,
        "ads":       [],
        "kw":        [],
        "kw_weekly": [],
        "geo":       [],
        "budgets":   {},
        "build_date": today.isoformat(),
    }


def fetch_bing_weekly(sheet_id, credentials_file=None):
    """
    Read the "Bing Ads" tab from the colleague's transposed PPC sheet.

    Layout (each column = one week, col A = metric label):
      Row 1: empty
      Row 2: "Week"  — date range strings like "03.30 - 04.05"
      Row 3: Spent
      Row 4: Conversions
      Row 5: Cost/conv
      Row 6: Clicks (Search)
      Row 7: CTR (Search)
      Row 8: Free sign ups

    Returns a list of dicts sorted oldest-first (complete weeks only):
      {
        week_start:     "YYYY-MM-DD"  (Monday)
        m_spend:        float
        m_clicks:       int
        m_impressions:  int           (always 0 — not in sheet)
        m_conversions:  float
        m_ctr:          float
        m_free_signups: int
      }
    """
    sheets = _get_sheets_service(credentials_file)
    result = _execute(sheets.values().get(
        spreadsheetId=sheet_id,
        range="'Bing Ads'!A1:ZZ20",
    ))
    raw = result.get("values", [])

    max_cols = max((len(r) for r in raw), default=0)
    rows = [r + [""] * (max_cols - len(r)) for r in raw]

    if len(rows) < 8:
        return []

    week_row    = rows[1]   # "Week" date-range labels
    spent_row   = rows[2]
    conv_row    = rows[3]
    # rows[4] = Cost/conv — skipped
    clicks_row  = rows[5]
    ctr_row     = rows[6]
    signups_row = rows[7]

    today       = date.today()
    this_monday = today - timedelta(days=today.weekday())

    def _parse_week_label(label):
        """
        "03.30 - 04.05" → Monday date on or before the start date.
        Year: if start month <= current month → current year, else prior year.
        """
        label = label.strip()
        if not label or label.lower() == "week":
            return None
        try:
            left  = label.split("-")[0].strip()
            parts = left.split(".")
            if len(parts) != 2:
                return None
            month, day = int(parts[0]), int(parts[1])
            if month > today.month + 2:
                year -= 1
            d = date(year, month, day)
            return d - timedelta(days=d.weekday())   # snap to Monday
        except (ValueError, IndexError):
            return None

    def _f(v):
        try:    return round(float(str(v).replace("$","").replace(",","").replace("%","").strip()), 2)
        except: return 0.0

    def _i(v):
        try:    return int(float(str(v).replace(",","").strip()))
        except: return 0

    seen = {}
    for col in range(1, max_cols):
        label = week_row[col] if col < len(week_row) else ""
        if not label:
            continue
        ws = _parse_week_label(label)
        if ws is None or ws >= this_monday:
            continue
        ws_str = ws.isoformat()
        seen[ws_str] = {
            "week_start":     ws_str,
            "m_spend":        _f(spent_row[col]   if col < len(spent_row)   else ""),
            "m_clicks":       _i(clicks_row[col]  if col < len(clicks_row)  else ""),
            "m_impressions":  0,
            "m_conversions":  _f(conv_row[col]    if col < len(conv_row)    else ""),
            "m_ctr":          _f(ctr_row[col]     if col < len(ctr_row)     else ""),
            "m_free_signups": _i(signups_row[col] if col < len(signups_row) else ""),
        }

    return sorted(seen.values(), key=lambda r: r["week_start"])


def fetch_channel_conversions_data(sheet_id=None, credentials_file=None) -> dict:
    """
    Read every "Week N - ..." tab from the "Weekly Conversion & Signups
    channels, MASTER doc" Google Sheet (columns: Level, Title, Registered,
    Conversions — Level is uniformly 1 in every tab checked and is not
    currently meaningful) and classify each Title into a GA4 channel via
    scripts.shared.title_classifier, so it can be joined against live GA4
    Traffic data by channel.

    Registered -> "Free", Conversions -> "Paid" (confirmed directly, not
    assumed — this sheet has no dollar/revenue figures at all).

    Returns:
      {
        "weeklyConversions":  {channel: {weekKey: {free, paid}}},
        "monthlyConversions": {channel: {monthKey: {free, paid}}},
        "unclassifiedTitles": {title: {free, paid}},  # fell to Other (Unclassified)
        "referralTitles":     {title: {free, paid}},  # fell to the generic Referral fallback
        "weekCount": int,
      }

    weekKey is a Monday ISO date string, matching the GA4 client's week
    convention exactly, so the two can be joined directly by key.

    Month aggregation splits each week's Free/Paid proportionally by how
    many of its 7 days fall in each calendar month (assumes activity is
    evenly spread across the week — the sheet has no daily breakdown to
    verify this against, so it's the best available approximation), per
    direct instruction to favor accuracy for true month-over-month reads.
    """
    if sheet_id is None:
        sheet_id = CHANNEL_PERF_SHEET_ID
    if not sheet_id:
        raise ValueError("No sheet_id provided and CHANNEL_PERF_SHEET_ID is not set")

    def _int(v):
        try:
            return int(float(str(v).replace(",", "").strip()))
        except (ValueError, TypeError):
            return 0

    sheets = _get_sheets_service(credentials_file)

    meta = _execute(sheets.get(spreadsheetId=sheet_id))
    all_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]

    week_re = re.compile(r"^Week (\d+)\s*-")
    week_tabs = []
    for t in all_titles:
        m = week_re.match(t)
        if m:
            week_tabs.append((int(m.group(1)), t))
    week_tabs.sort()

    weekly = defaultdict(lambda: defaultdict(lambda: {"free": 0, "paid": 0}))
    unclassified = defaultdict(lambda: {"free": 0, "paid": 0})
    referral_titles = defaultdict(lambda: {"free": 0, "paid": 0})
    week_keys = []

    print(f"⏳  Pulling channel conversions — {len(week_tabs)} week tabs …")
    for week_num, tab_title in week_tabs:
        monday = CHANNEL_PERF_WEEK1_MONDAY + timedelta(weeks=week_num - 1)
        week_key = monday.isoformat()
        week_keys.append(week_key)

        result = _execute(sheets.values().get(
            spreadsheetId=sheet_id,
            range=f"'{tab_title}'!A2:D",
        ))
        for row in result.get("values", []):
            if len(row) < 4:
                continue
            title, registered, conversions = row[1], row[2], row[3]
            reg, conv = _int(registered), _int(conversions)
            channel = classify_title(title)
            weekly[channel][week_key]["free"] += reg
            weekly[channel][week_key]["paid"] += conv
            if channel == OTHER_UNCLASSIFIED:
                unclassified[title]["free"] += reg
                unclassified[title]["paid"] += conv
            elif channel == "Referral":
                referral_titles[title]["free"] += reg
                referral_titles[title]["paid"] += conv

    # Month aggregation — proportional day-count split across month boundaries.
    monthly = defaultdict(lambda: defaultdict(lambda: {"free": 0.0, "paid": 0.0}))
    for week_num, tab_title in week_tabs:
        monday = CHANNEL_PERF_WEEK1_MONDAY + timedelta(weeks=week_num - 1)
        week_key = monday.isoformat()
        day_counts = defaultdict(int)
        for d in range(7):
            day = monday + timedelta(days=d)
            day_counts[f"{day.year:04d}-{day.month:02d}"] += 1
        for channel, week_map in weekly.items():
            vals = week_map.get(week_key)
            if not vals:
                continue
            for month_key, days in day_counts.items():
                frac = days / 7.0
                monthly[channel][month_key]["free"] += vals["free"] * frac
                monthly[channel][month_key]["paid"] += vals["paid"] * frac

    monthly_rounded = {
        ch: {mk: {"free": round(v["free"]), "paid": round(v["paid"])} for mk, v in mmap.items()}
        for ch, mmap in monthly.items()
    }
    weekly_plain = {ch: dict(wmap) for ch, wmap in weekly.items()}

    print(f"✅  Channel conversions collected — {len(week_keys)} weeks, "
          f"{len(unclassified)} unclassified titles, {len(referral_titles)} referral titles")

    return {
        "weeklyConversions": weekly_plain,
        "monthlyConversions": monthly_rounded,
        "unclassifiedTitles": dict(unclassified),
        "referralTitles": dict(referral_titles),
        "weekCount": len(week_tabs),
    }


# ── FIBBLER SNAPSHOT FUNCTIONS ────────────────────────────────────────────────
# These write/read a "Fibbler Snapshots" tab in the existing HUBSPOT_SHEET_ID
# Google Sheet so we can compute WoW deltas for Fibbler metrics across weekly
# builds.  The GA4_SERVICE_ACCOUNT_KEY service account already has Sheets
# access for that spreadsheet (read); write access is granted by the same
# service account credential — confirm the Sheet is shared with the service
# account email with at least Editor permission.

_SNAPSHOT_TAB     = "Fibbler Snapshots"
_SNAPSHOT_HEADERS = [
    "snapshot_date",
    "pipeline_value",
    "pipeline_deal_count",
    "closed_won_value",
    "closed_won_count",
    "very_high_engagement_count",
]


def _ensure_snapshot_tab(sheets_rw, sheet_id: str) -> None:
    """Create the Fibbler Snapshots tab with headers if it doesn't exist."""
    from googleapiclient.errors import HttpError

    # Check if tab already exists
    meta = _execute(sheets_rw.get(spreadsheetId=sheet_id))
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
    if _SNAPSHOT_TAB in existing:
        return

    print(f"  Creating '{_SNAPSHOT_TAB}' tab in spreadsheet…")
    _execute(sheets_rw.batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": _SNAPSHOT_TAB}}}]},
    ))

    # Write header row
    _execute(sheets_rw.values().update(
        spreadsheetId=sheet_id,
        range=f"'{_SNAPSHOT_TAB}'!A1",
        valueInputOption="RAW",
        body={"values": [_SNAPSHOT_HEADERS]},
    ))
    print(f"  Header row written to '{_SNAPSHOT_TAB}'.")


def write_fibbler_snapshot(
    sheet_id: str,
    snapshot_date: str,
    pipeline_value: float,
    pipeline_deal_count: int,
    closed_won_value: float,
    closed_won_count: int,
    very_high_count: int,
    credentials_file: str | None = None,
) -> None:
    """
    Append one row to the 'Fibbler Snapshots' tab, creating the tab (with
    headers) if it doesn't already exist.

    Args:
        sheet_id:            The Google Sheet ID (use HUBSPOT_SHEET_ID).
        snapshot_date:       Date string "YYYY-MM-DD" (the Monday build ran).
        pipeline_value:      Fibbler-influenced pipeline value this week.
        pipeline_deal_count: Number of influenced pipeline deals this week.
        closed_won_value:    Fibbler-influenced closed-won revenue this week.
        closed_won_count:    Number of influenced closed-won deals this week.
        very_high_count:     Count of companies with VERY_HIGH engagement.
    """
    sheets = _get_sheets_service_rw(credentials_file)
    _ensure_snapshot_tab(sheets, sheet_id)

    row = [
        snapshot_date,
        round(pipeline_value, 2),
        pipeline_deal_count,
        round(closed_won_value, 2),
        closed_won_count,
        very_high_count,
    ]
    _execute(sheets.values().append(
        spreadsheetId=sheet_id,
        range=f"'{_SNAPSHOT_TAB}'!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ))
    print(f"  Snapshot written: {row}")


def read_last_fibbler_snapshot(
    sheet_id: str,
    credentials_file: str | None = None,
) -> dict:
    """
    Read the most recent row from 'Fibbler Snapshots' and return it as a dict.

    Returns all-zeros with no_prior_snapshot=True when the tab doesn't exist
    or contains only the header row (i.e. first build after deployment).

    Returns:
        {
          "snapshot_date":           str | None,
          "pipeline_value":          float,
          "pipeline_deal_count":     int,
          "closed_won_value":        float,
          "closed_won_count":        int,
          "very_high_engagement_count": int,
          "no_prior_snapshot":       bool,
        }
    """
    from googleapiclient.errors import HttpError

    _ZERO = {
        "snapshot_date":              None,
        "pipeline_value":             0.0,
        "pipeline_deal_count":        0,
        "closed_won_value":           0.0,
        "closed_won_count":           0,
        "very_high_engagement_count": 0,
        "no_prior_snapshot":          True,
    }

    sheets = _get_sheets_service(credentials_file)
    try:
        result = _execute(sheets.values().get(
            spreadsheetId=sheet_id,
            range=f"'{_SNAPSHOT_TAB}'!A:F",
        ))
    except HttpError as exc:
        # Tab doesn't exist yet (400) or other access error
        print(f"  No prior snapshot: {exc}")
        return _ZERO

    rows = result.get("values", [])
    # rows[0] is header; data rows start at index 1
    data_rows = [r for r in rows[1:] if r and any(str(c).strip() for c in r)]
    if not data_rows:
        print("  No prior snapshot rows found.")
        return _ZERO

    last = data_rows[-1]

    def _f(v):
        try: return float(str(v).replace(",", "").strip())
        except (ValueError, TypeError): return 0.0

    def _i(v):
        try: return int(float(str(v).replace(",", "").strip()))
        except (ValueError, TypeError): return 0

    snapshot = {
        "snapshot_date":              str(last[0]) if len(last) > 0 else None,
        "pipeline_value":             _f(last[1])  if len(last) > 1 else 0.0,
        "pipeline_deal_count":        _i(last[2])  if len(last) > 2 else 0,
        "closed_won_value":           _f(last[3])  if len(last) > 3 else 0.0,
        "closed_won_count":           _i(last[4])  if len(last) > 4 else 0,
        "very_high_engagement_count": _i(last[5])  if len(last) > 5 else 0,
        "no_prior_snapshot":          False,
    }
    print(f"  Prior snapshot: {snapshot['snapshot_date']} — "
          f"pipeline=${snapshot['pipeline_value']:,.0f}, "
          f"veryHigh={snapshot['very_high_engagement_count']}")
    return snapshot

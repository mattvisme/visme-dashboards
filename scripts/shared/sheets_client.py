"""
scripts/shared/sheets_client.py
Shared Google Sheets reader for HubSpot, Amplitude, PPC, and GSC data.
"""

import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

HUBSPOT_SHEET_ID   = os.environ.get("HUBSPOT_SHEET_ID",
                                     "1TsDySDrmgSQEUjunQg77twgUS1fGgZIC71IbX-bAz1s")
AMPLITUDE_SHEET_ID = os.environ.get("AMPLITUDE_SHEET_ID",
                                     "11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw")
PPC_SHEET_ID       = os.environ.get("PPC_SHEET_ID",
                                     "11YiWr1aHhwBto9JrgwnSGJLtyq1KEfJvs5ZRbkoWKho")
GSC_SHEET_ID       = os.environ.get("GSC_SHEET_ID", "")


def _get_sheets_service(credentials_file=None):
    """Build an authenticated Google Sheets service."""
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

    creds = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
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
    result = sheets.values().get(spreadsheetId=sheet_id, range="Weekly Summary!A2:G").execute()
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
    result2 = sheets.values().get(spreadsheetId=sheet_id, range="Weekly Channels!A2:F").execute()
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
        result = sheets.values().get(
            spreadsheetId=sheet_id,
            range=f"'{tab_name}'!A2:E"
        ).execute()
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
    result = sheets.values().get(
        spreadsheetId=sheet_id, range="raw_campaign_daily!A:H"
    ).execute()
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
    result2 = sheets.values().get(
        spreadsheetId=sheet_id, range="raw_conv_actions_daily!A:F"
    ).execute()
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
    result = sheets.values().get(spreadsheetId=sheet_id, range="gsc_weekly!A2:E").execute()
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
    start_date = all_weeks[0]  if all_weeks else ""
    end_date   = all_weeks[-1] if all_weeks else ""
    print(f"    {len(all_weeks)} weeks  ({skipped} skipped)  endDate={end_date}")

    # ── dimension windows (queries / pages / countries) ───────────────────────
    def read_window_tab(tab_name, key_field):
        print(f"  Pulling GSC '{tab_name}'…")
        res = sheets.values().get(spreadsheetId=sheet_id,
                                  range=f"{tab_name}!A2:G").execute()
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
        "ctrByPos":       {},
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
        if n.startswith("GS_"):    return "Search"
        if n.startswith("GV_"):    return "Video"
        if n.startswith("GD_"):    return "Display"
        if n.startswith("PMAX_") or n.startswith("PM_"): return "PMax"
        return "Other"

    print("Google Ads (sheet): reading raw_campaign_daily...")
    result = sheets.values().get(
        spreadsheetId=sheet_id, range="raw_campaign_daily!A:H"
    ).execute()
    rows = result.get("values", [])[1:]   # skip header

    today       = date.today()
    this_monday = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")

    # Weekly accumulators
    w_spend = {}; w_impr = {}; w_clicks = {}; w_convs = {}

    # Campaign accumulators (lifetime totals)
    c_spend = {}; c_impr = {}; c_clicks = {}; c_convs = {}; c_type = {}

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

        c_spend[camp]  = c_spend.get(camp, 0.0)  + cost
        c_impr[camp]   = c_impr.get(camp, 0.0)   + impr
        c_clicks[camp] = c_clicks.get(camp, 0.0) + clk
        c_convs[camp]  = c_convs.get(camp, 0.0)  + conv
        if camp not in c_type:
            c_type[camp] = _infer_type(camp)

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
                "name":        camp,
                "type":        c_type[camp],
                "spend":       round(c_spend[camp], 2),
                "clicks":      int(c_clicks[camp]),
                "impressions": int(c_impr[camp]),
                "conversions": round(c_convs[camp], 2),
            }
            for camp in c_spend
        ],
        key=lambda r: r["spend"],
        reverse=True,
    )
    print(f"  -> {len(camps)} campaigns")

    return {
        "weekly":    weekly,
        "camps":     camps,
        "ads":       [],
        "kw":        [],
        "kw_weekly": [],
        "geo":       {},
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
    result = sheets.values().get(
        spreadsheetId=sheet_id,
        range="'Bing Ads'!A1:ZZ20",
    ).execute()
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
            year = today.year
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

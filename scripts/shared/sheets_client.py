"""
scripts/shared/sheets_client.py
Shared Google Sheets reader for HubSpot and Amplitude data.
Extracted from update_hubspot.py and update_amplitude.py in mattvisme/visme-dashboard.
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
    result = sheets.values().get(spreadsheetId=sheet_id, range="Weekly Summary!A2:F").execute()
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
            "leads":    _parse_float(row[1] if len(row) > 1 else None),
            "mqls":     _parse_float(row[2] if len(row) > 2 else None),
            "deals":    _parse_float(row[3] if len(row) > 3 else None),
            "pipeline": _parse_float(row[4] if len(row) > 4 else None),
            "revenue":  _parse_float(row[5] if len(row) > 5 else None),
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

    all_dates = sorted(set(list(summary.keys()) + list(channels.keys())))
    last_date = all_dates[-1] if all_dates else ""

    payload = {
        "weeks":      all_dates,
        "weekLabels": [_fmt_label(d) for d in all_dates],
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
    sorted_dates = sorted(merged.keys())
    print(f"  Amplitude merged: {len(sorted_dates)} unique weeks "
          f"({sorted_dates[0] if sorted_dates else '—'} → {sorted_dates[-1] if sorted_dates else '—'})")

    payload = {
        "weeks":       sorted_dates,
        "weekLabels":  [_fmt_label(d) for d in sorted_dates],
        "signups":     {d: merged[d]["signups"]     for d in sorted_dates},
        "upgrades":    {d: merged[d]["upgrades"]    for d in sorted_dates},
        "activations": {d: merged[d]["activations"] for d in sorted_dates},
        "cr":          {d: merged[d]["cr"]          for d in sorted_dates},
        "lastDate":    sorted_dates[-1] if sorted_dates else "",
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
            "weeks":   ["YYYY-MM-DD", ...],   # Monday boundaries, most-recent-first
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

    # ── Assemble weeks list (most-recent-first) ───────────────────────────────
    all_weeks = sorted(w_spend.keys(), reverse=True)
    print(f"  PPC weeks found: {len(all_weeks)}")

    today_str = date.today().strftime("%Y-%m-%d")

    payload = {
        "generatedAt": today_str,
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

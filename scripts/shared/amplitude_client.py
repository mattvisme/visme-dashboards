#!/usr/bin/env python3
"""
scripts/shared/amplitude_client.py
Fetches weekly PLG metrics directly from the Amplitude HTTP API.

Environment variables:
    AMPLITUDE_API_KEY     Amplitude project API key
    AMPLITUDE_API_SECRET  Amplitude project Secret key
"""

import base64
import json
import os
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_credentials():
    api_key = os.environ.get("AMPLITUDE_API_KEY", "")
    secret   = os.environ.get("AMPLITUDE_API_SECRET", "")
    if not api_key or not secret:
        raise EnvironmentError(
            "AMPLITUDE_API_KEY and AMPLITUDE_API_SECRET must be set."
        )
    return api_key, secret


def _basic_auth_header(api_key: str, secret: str) -> str:
    token = base64.b64encode(f"{api_key}:{secret}".encode()).decode()
    return f"Basic {token}"


def _fetch_event(event_name: str, start: str, end: str, interval: int,
                 auth_header: str, filters: list = None) -> dict:
    """
    Call Amplitude /api/2/events/segmentation for a single event.

    Args:
        event_name: Amplitude event_type string, e.g. "Sign Up Completed"
        start:      YYYYMMDD string
        end:        YYYYMMDD string
        interval:   7 for weekly
        auth_header: pre-built Basic auth string
        filters:    Optional list of Amplitude user/event property filters, e.g.
                    [{"subprop_type":"user","subprop_key":"platform",
                      "subprop_op":"is","subprop_value":["Web"]}]

    Returns:
        Parsed JSON response dict
    """
    # Match JS: JSON.stringify (no spaces) + encodeURIComponent (%20, not +)
    e_json  = json.dumps({"event_type": event_name}, separators=(",", ":"))
    e_param = urllib.parse.quote(e_json, safe="")
    url = (
        f"https://amplitude.com/api/2/events/segmentation"
        f"?e={e_param}&start={start}&end={end}&i={interval}"
    )
    if filters:
        f_param = urllib.parse.quote(json.dumps(filters, separators=(",", ":")), safe="")
        url += f"&filters={f_param}"
    import time as _time
    req = urllib.request.Request(url, headers={"Authorization": auth_header})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
            break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode(errors="replace")
            raise RuntimeError(
                f"Amplitude API {exc.code} for '{event_name}': {error_body}"
            ) from exc
        except (TimeoutError, OSError) as exc:
            if attempt == 3:
                raise RuntimeError(
                    f"Amplitude API timed out for '{event_name}' after 4 attempts"
                ) from exc
            wait = 15 * (2 ** attempt)  # 15s, 30s, 60s
            print(f"  Amplitude timeout (attempt {attempt + 1}/4), retrying in {wait}s…")
            _time.sleep(wait)
    if "data" not in body:
        raise RuntimeError(
            f"Amplitude API error for event '{event_name}': {body}"
        )
    return body


def _fmt_label(date_str: str) -> str:
    """Format 'YYYY-MM-DD' -> 'Jan 5' style label."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%b %-d") if os.name != "nt" else dt.strftime("%b %#d")


def _fetch_retention(start_event: str, start: str, end: str,
                     auth_header: str) -> dict:
    """
    Call Amplitude /api/2/retention for signup cohort D7 and D30 retention.

    Args:
        start_event: The cohort-defining event, e.g. "Sign Up Completed"
        start:       YYYYMMDD — first cohort date
        end:         YYYYMMDD — last cohort date
        auth_header: pre-built Basic auth string

    Returns:
        Dict mapping cohort date strings ("YYYY-MM-DD") to
        {"d7": float|None, "d30": float|None} where values are percentages.
        Returns {} on any API error so the build never fails.
    """
    se = urllib.parse.quote(
        json.dumps({"event_type": start_event}, separators=(",", ":")), safe=""
    )
    # Return event: "Project Created" — "of users who signed up, what % created
    # a project within N days?" More meaningful than generic _active for PLG.
    # Note: _active is a UI-only magic token; the HTTP API rejects it with 400.
    re_ = urllib.parse.quote(
        json.dumps({"event_type": "Project Created"}, separators=(",", ":")), safe=""
    )
    # i=1 → daily cohorts; n=32 gives headroom for D30 data.
    # type=n-day: N-Day retention (user returned on or after day N).
    # type is required — omitting it causes 400 "Invalid chart definition".
    url = (
        f"https://amplitude.com/api/2/retention"
        f"?se={se}&re={re_}&startdate={start}&enddate={end}&i=1&n=32&type=n-day"
    )
    print(f"    Retention URL: {url}")
    req = urllib.request.Request(url, headers={"Authorization": auth_header})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode()
            body = json.loads(raw)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(errors="replace")
        print(f"    WARNING: Retention API HTTP {exc.code}: {error_body[:300]}")
        return {}
    except Exception as exc:
        print(f"    WARNING: Retention API failed ({exc}); skipping D7/D30.")
        return {}

    print(f"    Retention body keys: {list(body.keys())}")
    data = body.get("data", {})
    if not data:
        print(f"    WARNING: Retention body has no 'data' key. Full body: {str(body)[:500]}")
        return {}

    print(f"    Retention data keys: {list(data.keys())}")
    x_vals  = data.get("xValues", [])
    series  = data.get("series", [])
    print(f"    Retention xValues ({len(x_vals)}): {x_vals[:5]}")
    print(f"    Retention series rows: {len(series)}, first row length: {len(series[0]) if series else 0}")

    result = {}
    for i, x in enumerate(x_vals):
        # Parse date — Amplitude may return "YYYY-MM-DD" or "YYYYMMDD"
        try:
            dt = datetime.strptime(x, "%Y-%m-%d")
        except ValueError:
            try:
                dt = datetime.strptime(x, "%Y%m%d")
            except ValueError:
                print(f"    WARNING: Unrecognised retention date format: {x!r}")
                continue
        key = dt.strftime("%Y-%m-%d")
        row = series[i] if i < len(series) else []
        # series[i][n] = retention % n days after cohort start (index 0 = 100%)
        result[key] = {
            "d7":  round(row[7],  2) if len(row) > 7  and row[7]  is not None else None,
            "d30": round(row[30], 2) if len(row) > 30 and row[30] is not None else None,
        }
    print(f"    Retention: {len(result)} cohort dates returned")
    if result:
        sample_key = next(iter(result))
        print(f"    Retention sample ({sample_key}): {result[sample_key]}")
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_amplitude_data() -> dict:
    """
    Pull weekly PLG metrics from the Amplitude API.

    Fetches three events (Sign Up Completed, Upgrade Completed, Project Created)
    using the /api/2/events/segmentation endpoint with i=7 (weekly intervals).
    The Amplitude API limits weekly queries to ~1 year, so we make two calls
    per event (current year + prior year) to cover the 2-year window the
    dashboard needs for YoY comparison.
    CR is computed as upgrades / signups per week.

    Returns the same payload shape as the legacy sheets_client version:
        {
          weeks:       [date_str, ...],          # Monday boundaries, oldest-first
          weekLabels:  [label_str, ...],          # "Jan 5" style, keyed to week-end Sunday
          signups:     {date_str: int},
          upgrades:    {date_str: int},
          activations: {date_str: int},
          cr:          {date_str: float | None},
          lastDate:    date_str,                  # Sunday of last complete week
        }
    """
    api_key, secret = _get_credentials()
    auth = _basic_auth_header(api_key, secret)

    today      = date.today()
    end_date   = today.strftime("%Y%m%d")
    # Split into two ~12-month windows to stay within Amplitude's range limit
    mid_date   = (today - timedelta(days=365)).strftime("%Y%m%d")
    start_date = (today - timedelta(days=730)).strftime("%Y%m%d")

    event_map = {
        "Sign Up Completed": "signups",
        "Upgrade Completed": "upgrades",
        "Project Created":   "activations",
    }

    # Collect raw series per event keyed by YYYY-MM-DD date string
    raw: dict = {k: {} for k in event_map.values()}

    def _ingest(body: dict, key: str) -> None:
        x_values = body["data"]["xValues"]
        series   = body["data"]["series"][0]
        for x, v in zip(x_values, series):
            try:
                dt = datetime.strptime(x, "%Y-%m-%d")
            except ValueError:
                try:
                    dt = datetime.strptime(x, "%Y%m%d")
                except ValueError:
                    print(f"    Skipping unrecognised date: {x!r}")
                    continue
            raw[key][dt.strftime("%Y-%m-%d")] = int(v or 0)

    for event_name, key in event_map.items():
        print(f"  Fetching Amplitude '{event_name}' (prior year)...")
        _ingest(_fetch_event(event_name, start_date, mid_date, 7, auth), key)
        print(f"  Fetching Amplitude '{event_name}' (current year)...")
        _ingest(_fetch_event(event_name, mid_date, end_date, 7, auth), key)
        print(f"    {len(raw[key])} weeks total")

    # Web-only signups — Sign Up Completed filtered to platform=Web.
    # App signups are derived as total - web (no app-session denominator exists,
    # so only volumes are surfaced; no conversion rate is computed for app).
    _WEB_FILTER = [{"subprop_type": "user", "subprop_key": "platform",
                    "subprop_op": "is", "subprop_value": ["Web"]}]
    raw["webSignups"] = {}
    print("  Fetching Amplitude 'Sign Up Completed' (web-only, prior year)...")
    _ingest(_fetch_event("Sign Up Completed", start_date, mid_date, 7, auth, _WEB_FILTER), "webSignups")
    print("  Fetching Amplitude 'Sign Up Completed' (web-only, current year)...")
    _ingest(_fetch_event("Sign Up Completed", mid_date, end_date, 7, auth, _WEB_FILTER), "webSignups")
    print(f"    {len(raw['webSignups'])} weeks total")

    # Determine complete weeks only (exclude current incomplete week)
    this_monday = date.today() - timedelta(days=date.today().weekday())
    this_monday_str = this_monday.strftime("%Y-%m-%d")

    all_dates = sorted(
        {d for series in raw.values() for d in series}
        - {this_monday_str}
    )
    all_dates = [d for d in all_dates if d < this_monday_str]

    if not all_dates:
        raise RuntimeError("No complete weekly data returned from Amplitude.")

    print(f"  Amplitude: {len(all_dates)} complete weeks "
          f"({all_dates[0]} -> {all_dates[-1]})")

    # Free-to-paid conversion rate per week (stored as %, e.g. 0.83 = 0.83%)
    cr = {}
    for d in all_dates:
        su = raw["signups"].get(d, 0)
        up = raw["upgrades"].get(d, 0)
        cr[d] = round((up / su) * 100, 4) if su > 0 else None

    # Activation rate per week (activated / signups, stored as %)
    act_rate = {}
    for d in all_dates:
        su = raw["signups"].get(d, 0)
        ac = raw["activations"].get(d, 0)
        act_rate[d] = round((ac / su) * 100, 4) if su > 0 else None

    # lastDate = Sunday of the last complete week
    last_monday_dt = datetime.strptime(all_dates[-1], "%Y-%m-%d").date()
    last_date = (last_monday_dt + timedelta(days=6)).strftime("%Y-%m-%d")

    # hasFullHistory: True when data spans ≥54 weeks (valid YoY for all pills)
    first_monday_dt = datetime.strptime(all_dates[0], "%Y-%m-%d").date()
    has_full_history = (today - first_monday_dt).days >= 54 * 7
    print(f"  hasFullHistory={has_full_history} "
          f"(first week: {all_dates[0]}, span: {(today - first_monday_dt).days} days)")

    week_labels = [
        _fmt_label(
            (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")
        )
        for d in all_dates
    ]

    # App signups = total signups minus web-only signups (clamped to 0)
    app_signups = {
        d: max(0, raw["signups"].get(d, 0) - raw["webSignups"].get(d, 0))
        for d in all_dates
    }

    return {
        "weeks":          all_dates,
        "weekLabels":     week_labels,
        "signups":        {d: raw["signups"].get(d, 0)       for d in all_dates},
        "webSignups":     {d: raw["webSignups"].get(d, 0)    for d in all_dates},
        "appSignups":     app_signups,
        "upgrades":       {d: raw["upgrades"].get(d, 0)      for d in all_dates},
        "activations":    {d: raw["activations"].get(d, 0)   for d in all_dates},
        "cr":             cr,
        "actRate":        act_rate,
        "lastDate":       last_date,
        "hasFullHistory": has_full_history,
    }

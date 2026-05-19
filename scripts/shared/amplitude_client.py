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
                 auth_header: str) -> dict:
    """
    Call Amplitude /api/2/events/segmentation for a single event.

    Args:
        event_name: Amplitude event_type string, e.g. "Sign Up Completed"
        start:      YYYYMMDD string
        end:        YYYYMMDD string
        interval:   7 for weekly
        auth_header: pre-built Basic auth string

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
    req = urllib.request.Request(url, headers={"Authorization": auth_header})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    if "data" not in body:
        raise RuntimeError(
            f"Amplitude API error for event '{event_name}': {body}"
        )
    return body


def _fmt_label(date_str: str) -> str:
    """Format 'YYYY-MM-DD' -> 'Jan 5' style label."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%b %-d") if os.name != "nt" else dt.strftime("%b %#d")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_amplitude_data(start_date: str = "20240101") -> dict:
    """
    Pull weekly PLG metrics from the Amplitude API.

    Fetches three events (Sign Up Completed, Upgrade Completed, Project Created)
    using the /api/2/events/segmentation endpoint with i=7 (weekly intervals).
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

    end_date = date.today().strftime("%Y%m%d")

    event_map = {
        "Sign Up Completed": "signups",
        "Upgrade Completed": "upgrades",
        "Project Created":   "activations",
    }

    # Collect raw series per event keyed by xValues date string
    raw: dict = {k: {} for k in event_map.values()}

    for event_name, key in event_map.items():
        print(f"  Fetching Amplitude '{event_name}'...")
        body = _fetch_event(event_name, start_date, end_date, 7, auth)
        x_values = body["data"]["xValues"]   # list of date strings from Amplitude
        series   = body["data"]["series"][0] # list of counts
        for x, v in zip(x_values, series):
            # Normalise to YYYY-MM-DD (Amplitude weekly returns e.g. "2024-01-01")
            try:
                dt = datetime.strptime(x, "%Y-%m-%d")
            except ValueError:
                try:
                    dt = datetime.strptime(x, "%Y%m%d")
                except ValueError:
                    print(f"    Skipping unrecognised date format: {x!r}")
                    continue
            raw[key][dt.strftime("%Y-%m-%d")] = int(v or 0)
        print(f"    {len(raw[key])} weeks returned")

    # Determine complete weeks only (exclude current incomplete week)
    this_monday = date.today() - timedelta(days=date.today().weekday())
    this_monday_str = this_monday.strftime("%Y-%m-%d")

    all_dates = sorted(
        {d for series in raw.values() for d in series}
        - {this_monday_str}
    )
    # Keep only dates strictly before this Monday
    all_dates = [d for d in all_dates if d < this_monday_str]

    if not all_dates:
        raise RuntimeError("No complete weekly data returned from Amplitude.")

    print(f"  Amplitude: {len(all_dates)} complete weeks "
          f"({all_dates[0]} -> {all_dates[-1]})")

    # Build per-week free-to-paid conversion rate, stored as percentage number
    # (e.g. 0.83 means 0.83%) to match the dashboard's toFixed(2)+'%' display
    cr = {}
    for d in all_dates:
        su = raw["signups"].get(d, 0)
        up = raw["upgrades"].get(d, 0)
        cr[d] = round((up / su) * 100, 4) if su > 0 else None

    # lastDate = Sunday of the last complete week
    last_monday_dt = datetime.strptime(all_dates[-1], "%Y-%m-%d").date()
    last_date = (last_monday_dt + timedelta(days=6)).strftime("%Y-%m-%d")

    week_labels = [
        _fmt_label(
            (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")
        )
        for d in all_dates
    ]

    return {
        "weeks":       all_dates,
        "weekLabels":  week_labels,
        "signups":     {d: raw["signups"].get(d, 0)     for d in all_dates},
        "upgrades":    {d: raw["upgrades"].get(d, 0)    for d in all_dates},
        "activations": {d: raw["activations"].get(d, 0) for d in all_dates},
        "cr":          cr,
        "lastDate":    last_date,
    }

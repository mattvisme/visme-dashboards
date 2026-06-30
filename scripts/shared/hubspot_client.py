"""
scripts/shared/hubspot_client.py
HubSpot CRM API client for the Performance Marketing dashboard.

Functions:
    fetch_new_leads(selected_start, selected_end, comparison_start, comparison_end)
        → new leads for two explicit date windows + paired daily volume
    fetch_lead_journey(from_date, to_date)
        → contacts grouped by hs_lead_status within the given window
    fetch_lead_quality_trend(weeks=8)
        → avg lead score per week for last N weeks

Auth: HUBSPOT_ACCESS_TOKEN env var (HubSpot Private App token).
Required scopes: crm.objects.contacts.read

HubSpot CRM Search API: POST /crm/v3/objects/contacts/search
Hard cap: 10,000 results per query.  Where only counts are needed we use the
`total` field from a limit=1 request rather than paginating.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

HUBSPOT_BASE = "https://api.hubapi.com"

LEAD_SCORE_PROP = "lead_quality_score"

# hs_lead_status values — confirmed from HubSpot portal 2026-06-29.
# Two custom values (LinkedIn Outreach, Never Replied) use their display name
# as the internal name (HubSpot stores them verbatim).
LEAD_STATUSES = [
    ("NEW",                  "New"),
    ("OPEN",                 "Open"),
    ("IN_PROGRESS",          "In Progress"),
    ("OPEN_DEAL",            "Open Deal"),
    ("UNQUALIFIED",          "Unqualified"),
    ("LinkedIn Outreach",    "LinkedIn Outreach"),
    ("ATTEMPTED_TO_CONTACT", "Attempted to Contact"),
    ("Never Replied",        "Never Replied"),
    ("CONNECTED",            "Connected"),
    ("BAD_TIMING",           "Disqualified"),
]


# ── INTERNAL HELPERS ──────────────────────────────────────────────────────────

def _token() -> str:
    tok = os.environ.get("HUBSPOT_ACCESS_TOKEN", "").strip()
    if not tok:
        raise EnvironmentError(
            "HUBSPOT_ACCESS_TOKEN is not set. "
            "Add it to GitHub repository secrets."
        )
    return tok


def _request(method: str, path: str, body: dict | None = None,
             retries: int = 3) -> dict:
    """HubSpot API request with exponential-backoff retry on 429."""
    url = HUBSPOT_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Content-Type":  "application/json",
    }
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_bytes = exc.read()
            if exc.code == 429:
                wait = 10 * (attempt + 1)
                print(f"  ⚠️  HubSpot 429 rate-limit. Waiting {wait}s…")
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"HubSpot API error {exc.code} on {method} {path}: "
                f"{body_bytes.decode('utf-8', errors='replace')}"
            ) from exc
    raise RuntimeError(
        f"HubSpot request failed after {retries} retries: {method} {path}"
    )


def _ms(d: date) -> str:
    """Return millisecond-UTC-midnight timestamp string for a date."""
    import calendar
    return str(calendar.timegm(d.timetuple()) * 1000)


def _count_search(filter_groups: list, retries: int = 3) -> int:
    """
    Return the HubSpot search `total` for the given filter groups.
    Uses limit=1 — no pagination needed.
    """
    resp = _request("POST", "/crm/v3/objects/contacts/search", body={
        "filterGroups": filter_groups,
        "properties":   ["createdate"],
        "limit":        1,
    }, retries=retries)
    return resp.get("total", 0)


def _lead_source_groups(from_date: date, to_date: date) -> list:
    """
    Build filterGroups for "new leads" definition:
        (hs_object_source = FORM
         OR hs_analytics_source = PAID_SOCIAL
         OR hs_analytics_source = PAID_SEARCH)
        AND createdate IN [from_date, to_date)

    HubSpot: filters within a filterGroup are AND'd; filterGroups themselves
    are OR'd.  To express (A OR B OR C) AND (D AND E) we need one filterGroup
    per OR-term, each also containing the AND-conditions.
    """
    date_gte = {"propertyName": "createdate", "operator": "GTE", "value": _ms(from_date)}
    date_lt  = {"propertyName": "createdate", "operator": "LT",  "value": _ms(to_date)}
    return [
        {"filters": [{"propertyName": "hs_object_source",    "operator": "EQ", "value": "FORM"},         date_gte, date_lt]},
        {"filters": [{"propertyName": "hs_analytics_source", "operator": "EQ", "value": "PAID_SOCIAL"},  date_gte, date_lt]},
        {"filters": [{"propertyName": "hs_analytics_source", "operator": "EQ", "value": "PAID_SEARCH"},  date_gte, date_lt]},
    ]


# ── PUBLIC FUNCTIONS ──────────────────────────────────────────────────────────

def fetch_new_leads(selected_start: date, selected_end: date,
                    comparison_start: date, comparison_end: date) -> dict:
    """
    Return new lead counts and paired day-by-day volume for two date windows.

    "New lead" = contact where hs_object_source = FORM
                 OR hs_analytics_source IN (PAID_SOCIAL, PAID_SEARCH).

    All counts use the `total` field from a limit=1 search — no pagination.

    The two windows must span the same number of days.  The paired daily
    volume aligns selected day i to comparison day i so the grouped bar chart
    can show matching weekdays side by side.

    Returns:
        {
          "selected":    int,
          "comparison":  int,
          "wowDelta":    int,
          "wowPct":      float | None,   # None when comparison == 0
          "dailyVolume": [
            {
              "date":       "YYYY-MM-DD",  # date in selected window
              "compDate":   "YYYY-MM-DD",  # same-offset date in comparison window
              "weekday":    "Mon",
              "selected":   int,
              "comparison": int,
            },
            ...  # one entry per day in the selected window
          ]
        }
    """
    print(f"  Selected  ({selected_start} – {selected_end}) …")
    selected = _count_search(_lead_source_groups(selected_start, selected_end))

    print(f"  Comparison ({comparison_start} – {comparison_end}) …")
    comparison = _count_search(_lead_source_groups(comparison_start, comparison_end))

    span = (selected_end - selected_start).days
    daily_volume = []
    for i in range(span):
        sel_day = selected_start + timedelta(days=i)
        cmp_day = comparison_start + timedelta(days=i)
        s_count = _count_search(_lead_source_groups(sel_day, sel_day + timedelta(days=1)))
        c_count = _count_search(_lead_source_groups(cmp_day, cmp_day + timedelta(days=1)))
        daily_volume.append({
            "date":       sel_day.isoformat(),
            "compDate":   cmp_day.isoformat(),
            "weekday":    sel_day.strftime("%a"),
            "selected":   s_count,
            "comparison": c_count,
        })
        print(f"    {sel_day.strftime('%a')} {sel_day}: sel={s_count}  cmp={c_count}")

    delta = selected - comparison
    pct   = round(delta / comparison * 100, 1) if comparison > 0 else None

    return {
        "selected":    selected,
        "comparison":  comparison,
        "wowDelta":    delta,
        "wowPct":      pct,
        "dailyVolume": daily_volume,
    }


def fetch_lead_journey(from_date: date, to_date: date) -> dict:
    """
    Return contact counts per hs_lead_status, scoped to the same lead
    population as fetch_new_leads(): paid-social, paid-search, or form-sourced
    contacts created within [from_date, to_date).

    Returns:
        {
          "scopeNote": "Paid + form leads, last N days (X total)",
          "total":     int,
          "stages": {
            "New":                  int,
            "Open":                 int,
            "In Progress":          int,
            "Open Deal":            int,
            "Unqualified":          int,
            "LinkedIn Outreach":    int,
            "Attempted to Contact": int,
            "Never Replied":        int,
            "Connected":            int,
            "Disqualified":         int,
          }
        }
    """
    days = (to_date - from_date).days

    print(f"  Counting total leads in scope (last {days} days)…")
    total = _count_search(_lead_source_groups(from_date, to_date))

    stages = {}
    for api_value, label in LEAD_STATUSES:
        status_f = {"propertyName": "hs_lead_status", "operator": "EQ", "value": api_value}
        # Mirror _lead_source_groups exactly, adding hs_lead_status as an AND
        # condition inside each filterGroup (preserving the OR-across-groups logic).
        groups = [
            {"filters": grp["filters"] + [status_f]}
            for grp in _lead_source_groups(from_date, to_date)
        ]
        count = _count_search(groups)
        stages[label] = count
        print(f"  hs_lead_status={api_value}: {count}")

    return {
        "scopeNote": f"Paid + form leads, last {days} days ({total:,} total)",
        "total":     total,
        "stages":    stages,
    }


def fetch_lead_quality_trend(weeks: int = 8,
                             reference_date: date | None = None) -> dict:
    """
    Return average Lead Quality Score per week for the last N complete weeks.

    reference_date controls the trailing-window anchor (defaults to today).
    Pass a past date to compute the same 8-week window relative to that date
    so both WoW selector windows can show their own quality trend.

    Fetches up to 100 scored contacts per week (single page) and averages
    their scores.  This is a sample-based average — sufficient for trend
    visualisation.  Weeks with no scored contacts return avgScore=None.

    ⚠️  Property name is '{LEAD_SCORE_PROP}' — confirm before deploying.

    Returns:
        {{
          "weeks":     ["YYYY-MM-DD", ...],   # week-start Mondays, oldest first
          "avgScores": [float | None, ...]    # one entry per week
        }}
    """
    today       = reference_date or date.today()
    this_monday = today - timedelta(days=today.weekday())

    week_starts = [
        (this_monday - timedelta(weeks=i)).isoformat()
        for i in range(weeks, 0, -1)   # oldest first
    ]

    avg_scores = []
    for ws in week_starts:
        week_start_dt = date.fromisoformat(ws)
        week_end_dt   = week_start_dt + timedelta(days=7)

        resp = _request("POST", "/crm/v3/objects/contacts/search", body={
            "filterGroups": [{"filters": [
                {"propertyName": "createdate", "operator": "GTE", "value": _ms(week_start_dt)},
                {"propertyName": "createdate", "operator": "LT",  "value": _ms(week_end_dt)},
                {"propertyName": LEAD_SCORE_PROP, "operator": "HAS_PROPERTY"},
            ]}],
            "properties": [LEAD_SCORE_PROP],
            "limit": 100,
        })

        scores = []
        for result in resp.get("results", []):
            raw = (result.get("properties") or {}).get(LEAD_SCORE_PROP)
            try:
                scores.append(float(raw))
            except (TypeError, ValueError):
                pass

        avg = round(sum(scores) / len(scores), 2) if scores else None
        avg_scores.append(avg)
        print(f"  Week {ws}: {len(scores)} scored contacts, avg={avg}")

    return {"weeks": week_starts, "avgScores": avg_scores}

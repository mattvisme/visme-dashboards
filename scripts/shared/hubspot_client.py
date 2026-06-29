"""
scripts/shared/hubspot_client.py
HubSpot Private App API client for the visme-dashboards build system.

Authentication:
    Set HUBSPOT_ACCESS_TOKEN to a HubSpot Private App token with scopes:
        crm.objects.companies.read
        crm.objects.contacts.read

    ⚠️  HUBSPOT_ACCESS_TOKEN must be provisioned in GitHub repository secrets
        before the build_performance.py step will run in CI.

API version: HubSpot CRM API v3
Pagination:  All list/search endpoints use cursor-based pagination via the
             `after` field returned in `paging.next.after`.  Each page is
             capped at 100 results (HubSpot maximum for search endpoints).
"""

import os
import time
import urllib.request
import urllib.error
import json
from datetime import date, timedelta

HUBSPOT_BASE = "https://api.hubapi.com"

# ── FIBBLER CUSTOM PROPERTY NAMES ────────────────────────────────────────────
#
# Confirmed against HubSpot properties export on 2026-06-29.
# Fibbler embeds the LinkedIn Ad Account ID (502785047) in every property name.
# All properties live in the "companyinformation" group.
#
FIBBLER_PROPS = {
    "impressions30":        "fibbler_linkedin_ad_impressions_502785047_30_days",
    "clicks30":             "fibbler_linkedin_ad_clicks_502785047_30_days",
    "engagements30":        "fibbler_linkedin_ad_engagements_502785047_30_days",
    "engagementLevel":      "fibbler_linkedin_engagement_level_502785047_30_days",
    "organicImpressions30": "fibbler_linkedin_organic_impressions_502785047_30_days",
    "organicEngagements30": "fibbler_linkedin_organic_engagements_502785047_30_days",
}

# Standard HubSpot company properties we also pull alongside Fibbler data.
STANDARD_COMPANY_PROPS = [
    "name",
    "domain",
    "industry",
    "numberofemployees",
    "hs_pipeline_stage",
    "lifecyclestage",
    "amount",               # associated deal value if synced to company record
]


def _token() -> str:
    """Return the HubSpot access token from env, raising clearly if absent."""
    token = os.environ.get("HUBSPOT_ACCESS_TOKEN", "").strip()
    if not token:
        raise EnvironmentError(
            "HUBSPOT_ACCESS_TOKEN is not set. "
            "Create a HubSpot Private App token and export it before running."
        )
    return token


def _request(method: str, path: str, body: dict | None = None, retries: int = 3) -> dict:
    """
    Minimal HTTP helper using urllib (no third-party deps).
    Handles JSON serialisation, auth header, and 429/5xx retry with backoff.
    """
    url = HUBSPOT_BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Content-Type":  "application/json",
    }

    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors="replace")
            if exc.code == 429 or exc.code >= 500:
                wait = 10 * (2 ** attempt)
                print(f"  HubSpot {exc.code} (attempt {attempt + 1}/{retries}), "
                      f"retrying in {wait}s … {body_text[:120]}")
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"HubSpot API error {exc.code} on {method} {path}: {body_text}"
            ) from exc

    raise RuntimeError(f"HubSpot API request failed after {retries} attempts: {method} {path}")


# ── PUBLIC FUNCTIONS ──────────────────────────────────────────────────────────

def fetch_fibbler_companies() -> list[dict]:
    """
    Return all HubSpot company records that have a non-null value for at
    least one Fibbler LinkedIn property.

    Each returned dict has keys:
        name, domain, industry, employees (int), engagementLevel (str),
        impressions30 (int), clicks30 (int), engagements30 (int),
        organicImpressions30 (int), organicEngagements30 (int),
        lifecyclestage (str), pipelineStage (str),
        hasOpenDeal (bool), dealValue (float)

    Pagination: uses cursor-based `after` pagination, fetching up to
    100 records per page until exhausted.

    Assumption: `amount` on the company record reflects the associated deal
    value.  If Visme stores deal value only on Deal objects (not synced to
    Company), `dealValue` will always be 0 and a separate Deals API query
    will be needed.
    """
    all_props = list(FIBBLER_PROPS.values()) + STANDARD_COMPANY_PROPS

    # Build OR filter: any Fibbler prop is known (non-null)
    filters = [
        {
            "propertyName": prop_name,
            "operator":     "HAS_PROPERTY",
        }
        for prop_name in FIBBLER_PROPS.values()
    ]
    filter_group = {"filters": filters}   # OR within a single filterGroup

    companies = []
    after = None
    page = 0

    while True:
        page += 1
        payload = {
            "filterGroups": [filter_group],
            "properties":   all_props,
            "limit":        100,
        }
        if after:
            payload["after"] = after

        print(f"  HubSpot Companies page {page} (after={after}) …")
        resp = _request("POST", "/crm/v3/objects/companies/search", body=payload)

        for result in resp.get("results", []):
            props = result.get("properties", {})

            def _int(key: str) -> int:
                v = props.get(key)
                if v is None or str(v).strip() in ("", "None"):
                    return 0
                try:
                    return int(float(v))
                except (ValueError, TypeError):
                    return 0

            def _str(key: str) -> str:
                v = props.get(key)
                return str(v).strip() if v is not None else ""

            deal_value = 0.0
            raw_amount = props.get("amount")
            if raw_amount not in (None, "", "None"):
                try:
                    deal_value = float(raw_amount)
                except (ValueError, TypeError):
                    pass

            companies.append({
                "name":                 _str("name"),
                "domain":               _str("domain"),
                "industry":             _str("industry"),
                "employees":            _int("numberofemployees"),
                "engagementLevel":      _str(FIBBLER_PROPS["engagementLevel"]),
                "impressions30":        _int(FIBBLER_PROPS["impressions30"]),
                "clicks30":             _int(FIBBLER_PROPS["clicks30"]),
                "engagements30":        _int(FIBBLER_PROPS["engagements30"]),
                "organicImpressions30": _int(FIBBLER_PROPS["organicImpressions30"]),
                "organicEngagements30": _int(FIBBLER_PROPS["organicEngagements30"]),
                "lifecyclestage":       _str("lifecyclestage"),
                "pipelineStage":        _str("hs_pipeline_stage"),
                "hasOpenDeal":          deal_value > 0,
                "dealValue":            deal_value,
            })

        # Advance cursor or stop
        after = (resp.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break

    print(f"  → {len(companies)} Fibbler company records fetched")
    return companies


def fetch_new_contacts_by_source(days: int = 30) -> dict[str, int]:
    """
    Return a count of HubSpot contacts created in the last `days` days,
    grouped by `hs_analytics_source` (HubSpot original source).

    The HubSpot CRM search API does not support server-side aggregation,
    so we page through all matching contacts and count client-side.

    Assumption: `hs_analytics_source` uses HubSpot's standard source enum
    values (ORGANIC_SEARCH, PAID_SEARCH, SOCIAL_MEDIA, PAID_SOCIAL,
    EMAIL_MARKETING, REFERRALS, DIRECT_TRAFFIC, OTHER_CAMPAIGNS, etc.).
    The exact set returned depends on what sources HubSpot has seen —
    we return whatever keys come back without normalising them.

    Assumption: contacts are filtered by `createdate` >= today - `days`.
    HubSpot's timestamp filter uses milliseconds since epoch.

    Returns: {source_name: count, ...}  e.g. {"ORGANIC_SEARCH": 142, ...}
    """
    cutoff_ms = int(
        (date.today() - timedelta(days=days)).strftime("%s")
        if hasattr(date.today(), "strftime")
        else (date.today() - timedelta(days=days)).timetuple()
    )
    # Cross-platform millisecond timestamp
    import calendar
    cutoff_dt = date.today() - timedelta(days=days)
    cutoff_ms = calendar.timegm(cutoff_dt.timetuple()) * 1000

    filter_group = {
        "filters": [
            {
                "propertyName": "createdate",
                "operator":     "GTE",
                "value":        str(cutoff_ms),
            }
        ]
    }

    counts: dict[str, int] = {}
    after  = None
    page   = 0
    total  = 0

    while True:
        page += 1
        payload = {
            "filterGroups": [filter_group],
            "properties":   ["hs_analytics_source"],
            "limit":        100,
        }
        if after:
            payload["after"] = after

        print(f"  HubSpot Contacts page {page} (after={after}) …")
        resp = _request("POST", "/crm/v3/objects/contacts/search", body=payload)

        for result in resp.get("results", []):
            source = (
                (result.get("properties") or {}).get("hs_analytics_source") or "UNKNOWN"
            ).strip()
            counts[source] = counts.get(source, 0) + 1
            total += 1

        after = (resp.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break

    print(f"  → {total} contacts fetched, {len(counts)} sources: {sorted(counts.keys())}")
    return counts

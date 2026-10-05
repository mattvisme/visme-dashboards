"""
scripts/shared/hubspot_client.py
HubSpot CRM API client for the Performance Marketing (LinkedIn Ads) dashboard.

Auth: HUBSPOT_ACCESS_TOKEN env var (HubSpot Private App token).
Required scopes: crm.objects.contacts.read, crm.objects.deals.read,
    crm.objects.owners.read (meetings are read via the contacts associations;
    the build prints the HubSpot error if a scope is missing).
Optional: oauth / account-info scope for the portal id used in record links
          (or set HUBSPOT_PORTAL_ID).
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HUBSPOT_BASE = "https://api.hubapi.com"


def _token() -> str:
    tok = os.environ.get("HUBSPOT_ACCESS_TOKEN", "").strip()
    if not tok:
        raise EnvironmentError(
            "HUBSPOT_ACCESS_TOKEN is not set. Add it to GitHub repository secrets."
        )
    return tok


def _request(method: str, path: str, body: dict | None = None, retries: int = 4) -> dict:
    """HubSpot API request with exponential-backoff retry on 429."""
    url = HUBSPOT_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 or exc.code >= 500:
                wait = 5 * (attempt + 1)
                print(f"  ⚠️  HubSpot {exc.code}. Waiting {wait}s…")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HubSpot API error {exc.code} on {method} {path}: {err}") from exc
    raise RuntimeError(f"HubSpot request failed after {retries} retries: {method} {path}")


def ms(iso_date: str) -> str:
    """'2026-06-01' → UTC-midnight epoch milliseconds (string), as HubSpot date filters want."""
    d = datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return str(int(d.timestamp() * 1000))


def search(object_type: str, filter_groups: list, properties: list,
           sorts: list | None = None, max_pages: int = 50) -> list:
    """Paginated CRM search. Returns every result (HubSpot caps one query at 10k)."""
    out, after = [], None
    for _ in range(max_pages):
        body = {"filterGroups": filter_groups, "properties": properties, "limit": 100}
        if sorts:
            body["sorts"] = sorts
        if after:
            body["after"] = after
        resp = _request("POST", f"/crm/v3/objects/{object_type}/search", body)
        out.extend(resp.get("results", []))
        after = ((resp.get("paging") or {}).get("next") or {}).get("after")
        time.sleep(0.25)  # search API allows ~4-5 req/s
        if not after:
            break
    return out


def batch_read(object_type: str, ids: list, properties: list) -> list:
    """Batch-read objects by id (100 per call)."""
    out = []
    ids = [str(i) for i in dict.fromkeys(ids)]
    for i in range(0, len(ids), 100):
        resp = _request("POST", f"/crm/v3/objects/{object_type}/batch/read", {
            "properties": properties,
            "inputs": [{"id": x} for x in ids[i:i + 100]],
        })
        out.extend(resp.get("results", []))
    return out


def associations(from_type: str, to_type: str, ids: list) -> dict:
    """Batch associations v4. Returns {from_id: [to_id, ...]}."""
    out = {}
    ids = [str(i) for i in dict.fromkeys(ids)]
    for i in range(0, len(ids), 1000):
        resp = _request("POST", f"/crm/v4/associations/{from_type}/{to_type}/batch/read",
                        {"inputs": [{"id": x} for x in ids[i:i + 1000]]})
        for r in resp.get("results", []):
            out[str(r["from"]["id"])] = [str(t["toObjectId"]) for t in r.get("to", [])]
    return out


def owners() -> dict:
    """{ownerId: 'First Last'} for every HubSpot owner."""
    out, after = {}, None
    while True:
        path = "/crm/v3/owners?limit=500&archived=false" + (f"&after={after}" if after else "")
        resp = _request("GET", path)
        for o in resp.get("results", []):
            name = f"{o.get('firstName') or ''} {o.get('lastName') or ''}".strip() or o.get("email", "")
            out[str(o["id"])] = name
        after = ((resp.get("paging") or {}).get("next") or {}).get("after")
        if not after:
            return out


def contact_url_template() -> str:
    """'https://app.hubspot.com/contacts/<portal>/record/0-1/{id}' or '' if the portal id is unknown."""
    pid = os.environ.get("HUBSPOT_PORTAL_ID", "").strip()
    if not pid:
        try:
            pid = str(_request("GET", "/account-info/v3/details").get("portalId", ""))
        except Exception:
            pid = ""
    return f"https://app.hubspot.com/contacts/{pid}/record/0-1/{{id}}" if pid else ""

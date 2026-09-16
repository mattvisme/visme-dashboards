"""
scripts/shared/firstpromoter_client.py
Shared FirstPromoter API v2 helper for the visme-dashboards build system.

Source of truth for affiliate referrals/conversions/revenue — tracked via
FirstPromoter's own referral links/cookies, not GA4 UTM attribution. Legacy
affiliates without expanded UTM tagging don't show up in GA4's "Affiliates"
channel group, so this is used in place of that channel for the Affiliates
dashboard row.
"""

import os
import time
from datetime import date, datetime, timedelta
from collections import defaultdict

import requests

API_BASE = "https://api.firstpromoter.com/api/v2"
WEEKS_HISTORY = 156


def _get_headers():
    api_key = os.environ["FIRSTPROMOTER_API_KEY"]
    account_id = os.environ["FIRSTPROMOTER_ACCOUNT_ID"]
    return {"Authorization": f"Bearer {api_key}", "Account-ID": account_id}


def _get_monday_str(dt: datetime) -> str:
    d = dt.date()
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


PAGE_DELAY_SECONDS = 0.6   # ~100 req/min, under FirstPromoter's observed ~100-130 req/min limit


def _paginate(path: str, params: dict) -> list[dict]:
    headers = _get_headers()
    results = []
    page = 1
    while True:
        page_params = {**params, "page": page}
        for attempt in range(4):
            try:
                resp = requests.get(f"{API_BASE}/{path}",
                                     headers=headers, params=page_params, timeout=30)
                if resp.status_code == 429:
                    if attempt == 3:
                        resp.raise_for_status()
                    wait = int(resp.headers.get("Retry-After", 15 * (2 ** attempt)))
                    print(f"  FirstPromoter rate limited (attempt {attempt + 1}/4), retrying in {wait}s")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 3:
                    raise
                wait = 15 * (2 ** attempt)
                print(f"  FirstPromoter API error (attempt {attempt + 1}/4), retrying in {wait}s: {e}")
                time.sleep(wait)
        batch = resp.json()
        if not batch:
            break
        results.extend(batch)
        page += 1
        time.sleep(PAGE_DELAY_SECONDS)
    return results


def _fetch_referrals(created_from: str, created_to: str) -> list[dict]:
    """Paginate GET /company/referrals filtered by created_at date range."""
    return _paginate("company/referrals", {
        "filters[created_at][from]": created_from,
        "filters[created_at][to]": created_to,
    })


def _fetch_commissions(created_from: str, created_to: str) -> list[dict]:
    """Paginate GET /company/commissions filtered by created_at date range.
    Each commission's sale_amount/amount are in cents."""
    return _paginate("company/commissions", {
        "filters[created_at][from]": created_from,
        "filters[created_at][to]": created_to,
    })


def fetch_affiliate_source_weekly(weeks: int = WEEKS_HISTORY) -> dict:
    """
    Fetch weekly affiliate signups, conversions, and revenue by traffic source.

    Returns:
      {
        "signups":     {source: {weekStart: count}},
        "conversions": {source: {weekStart: count}},
        "revenue":     {source: {weekStart: dollars}},
      }
    Referrals with no traffic_source are bucketed under "direct". Revenue is
    attributed to the source of the referral that generated the sale.
    """
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    start_dt = this_monday - timedelta(weeks=weeks)
    start_str, end_str = start_dt.isoformat(), today.isoformat()
    this_monday_str = this_monday.strftime("%Y-%m-%d")

    print(f"⏳  Pulling FirstPromoter referrals {start_str} → {end_str} …")
    referrals = _fetch_referrals(start_str, end_str)

    signups: dict = defaultdict(lambda: defaultdict(int))
    conversions: dict = defaultdict(lambda: defaultdict(int))
    referral_source = {}
    for r in referrals:
        source = r.get("traffic_source") or "direct"
        referral_source[r["id"]] = source

        created = datetime.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        w = _get_monday_str(created)
        if w < this_monday_str:
            signups[source][w] += 1

        if r.get("customer_since"):
            conv_w = _get_monday_str(datetime.strptime(r["customer_since"], "%Y-%m-%dT%H:%M:%SZ"))
            if conv_w < this_monday_str:
                conversions[source][conv_w] += 1

    print(f"⏳  Pulling FirstPromoter commissions {start_str} → {end_str} …")
    commissions = _fetch_commissions(start_str, end_str)

    revenue: dict = defaultdict(lambda: defaultdict(float))
    for c in commissions:
        rid = c.get("referral", {}).get("id")
        source = referral_source.get(rid, "direct")
        w = _get_monday_str(datetime.strptime(c["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
        if w < this_monday_str:
            revenue[source][w] += c.get("sale_amount", 0) / 100

    print(f"✅  FirstPromoter collected — {len(referrals)} referrals, "
          f"{len(commissions)} commissions, {len(signups)} sources")
    return {
        "signups": {s: dict(wk) for s, wk in signups.items()},
        "conversions": {s: dict(wk) for s, wk in conversions.items()},
        "revenue": {s: dict(wk) for s, wk in revenue.items()},
    }


def fetch_affiliate_traffic_by_period(start_date: date) -> dict:
    """
    Fetch affiliate signups by source, bucketed by both complete Mon-Sun week
    and complete calendar month, from start_date through the last complete
    period. Period keys match fetch_channel_performance_data()'s format
    (week: Monday ISO date; month: "YYYY-MM") so callers can drop this
    straight into CP.weeklyTraffic["Affiliates"] / CP.monthlyTraffic["Affiliates"]
    in place of GA4's channel-grouped sessions.
    """
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    this_month_start = date(today.year, today.month, 1)
    this_monday_str = this_monday.strftime("%Y-%m-%d")

    print(f"⏳  Pulling FirstPromoter referrals {start_date.isoformat()} → {today.isoformat()} …")
    referrals = _fetch_referrals(start_date.isoformat(), today.isoformat())

    weekly: dict = defaultdict(lambda: defaultdict(int))
    monthly: dict = defaultdict(lambda: defaultdict(int))
    for r in referrals:
        source = r.get("traffic_source") or "direct"
        created = datetime.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        cd = created.date()

        w = _get_monday_str(created)
        if w < this_monday_str:
            weekly[source][w] += 1

        if cd < this_month_start:
            monthly[source][f"{cd.year:04d}-{cd.month:02d}"] += 1

    print(f"✅  FirstPromoter collected — {len(referrals)} referrals, "
          f"{len(weekly)} weekly sources, {len(monthly)} monthly sources")
    return {
        "weeklyTraffic": {s: dict(wk) for s, wk in weekly.items()},
        "monthlyTraffic": {s: dict(mo) for s, mo in monthly.items()},
    }


if __name__ == "__main__":
    data = fetch_affiliate_source_weekly(weeks=8)
    for source in sorted(data["signups"], key=lambda s: -sum(data["signups"][s].values())):
        total_signups = sum(data["signups"][source].values())
        total_conversions = sum(data["conversions"].get(source, {}).values())
        total_revenue = sum(data["revenue"].get(source, {}).values())
        print(f"{source}: signups={total_signups} conversions={total_conversions} revenue=${total_revenue:.2f}")
    assert set(data.keys()) == {"signups", "conversions", "revenue"}

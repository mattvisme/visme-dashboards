#!/usr/bin/env python3
"""
scripts/build_performance.py
Builds performance/index.html — the LinkedIn Ads dashboard (June 1 to today).

Python port of the Claude artifact "LinkedIn Ads Dashboard" (Jon, Performance
Marketing). Same queries, filters and calculations, run server-side so the page
can be rebuilt weekly by GitHub Actions.

Data sources:
    HubSpot CRM API   → lead gen form leads, meetings, account funnel, demo requests
    Fibbler MCP       → spend, influenced pipeline / closed won / deals, company engagement

Environment variables required:
    HUBSPOT_ACCESS_TOKEN   HubSpot Private App token (contacts, deals, owners read)
    FIBBLER_API_KEY        Fibbler MCP API key (https://app.fibbler.co/mcp)
Optional:
    HUBSPOT_PORTAL_ID      Portal id for contact links (auto-detected if scope allows)
"""

import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared import hubspot_client as hs
from scripts.shared.fibbler_client import Fibbler
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(REPO_ROOT, "performance", "index.html")
OUTPUT = TEMPLATE

START_DATE = "2026-06-01"
START_MONTH = "2026-06"
LGF = "LinkedIn Lead Generation Ad"

SALES_PIPES = {"default", "7638623"}
WON = {"closedwon", "21981730"}
LOST = {"closedlost", "21981731"}
LC_RANK = {"subscriber": 0, "lead": 1, "marketingqualifiedlead": 2, "1369952279": 2,
           "salesqualifiedlead": 3, "opportunity": 4, "customer": 5, "evangelist": 5}
JUNK_CO = {"", "n a", "na", "none", "self", "self employed", "freelance", "freelancer", "student",
           "retired", "independent", "unemployed", "test", "x", "home", "personal"}
PERSONAL = {"gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
            "msn.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "gmx.com",
            "ymail.com"}
DEMO_FORMS = ["Main Sales Form - Site", "Support to Sales Lead Form",
              "ABM Sports LP MQL Form - AIBP", "ABM Insurance LP MQL Form"]
DEMO_EVENT = re.compile(r"talk to sales|support to sales|sales lead form|mql form", re.I)
VISME_DOMAIN = re.compile(r"(^|\.)visme\.co(m)?$")
SRC = {"PAID_SEARCH": "Paid search", "ORGANIC_SEARCH": "Organic search", "DIRECT_TRAFFIC": "Direct",
       "OTHER_CAMPAIGNS": "Other campaigns", "REFERRALS": "Referral", "OFFLINE": "Offline or CRM",
       "EMAIL_MARKETING": "Email", "SOCIAL_MEDIA": "Organic social", "PAID_SOCIAL": "Paid social",
       "AI_REFERRALS": "AI referral"}
OUTCOME_RANK = {"COMPLETED": 5, "UPCOMING": 4, "RESCHEDULED": 3, "NOTLOGGED": 2, "NO_SHOW": 1, "CANCELED": 0}
OUTCOME_LABEL = {"COMPLETED": ["Completed", "won"], "SCHEDULED": ["Scheduled", "sched"],
                 "NO_SHOW": ["No show", "lost"], "CANCELED": ["Canceled", "lost"],
                 "RESCHEDULED": ["Rescheduled", "sched"]}


# ── small helpers ─────────────────────────────────────────────────────────────

def cur_month() -> str:
    return date.today().strftime("%Y-%m")


def month_add(ym: str, n: int) -> str:
    y, m = map(int, ym.split("-"))
    m += n
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return f"{y}-{m:02d}"


def domain_of(email) -> str:
    m = re.search(r"@([^@\s>]+)$", str(email or "").lower().strip())
    return m.group(1) if m else ""


def norm_name(s) -> str:
    s = str(s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(the|fc|inc|llc|ltd|gmbh|co|kg|aa|club)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def full_name(p: dict) -> str:
    return f"{p.get('firstname') or ''} {p.get('lastname') or ''}".strip()


def num(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def stage_kind(stage) -> str:
    s = (stage or "").lower()
    if "closed won" in s:
        return "won"
    if "closed lost" in s:
        return "lost"
    return "open"


def is_lgf_event(name) -> bool:
    return str(name or "").startswith(LGF)


# ── HubSpot: leads ────────────────────────────────────────────────────────────

LEAD_PROPS = ["firstname", "lastname", "email", "company", "jobtitle", "createdate",
              "first_conversion_event_name", "recent_conversion_event_name", "form_filled",
              "lifecyclestage", "num_associated_deals"]


def load_leads() -> list:
    rows = hs.search("contacts", [{"filters": [
        {"propertyName": "hs_analytics_source", "operator": "EQ", "value": "PAID_SOCIAL"},
        {"propertyName": "hs_analytics_source_data_1", "operator": "EQ", "value": "LinkedIn"},
        {"propertyName": "createdate", "operator": "GTE", "value": hs.ms(START_DATE)}]}],
        LEAD_PROPS, sorts=[{"propertyName": "createdate", "direction": "ASCENDING"}])
    out = []
    for c in rows:
        p = c["properties"]
        is_lgf = is_lgf_event(p.get("first_conversion_event_name")) or \
            is_lgf_event(p.get("recent_conversion_event_name"))
        is_test = (p.get("company") or "").strip().lower() == "visme"
        if is_lgf and not is_test:
            out.append(c)
    return out


def lead_summary(leads: list) -> dict:
    months, forms = {}, {}
    for c in leads:
        p = c["properties"]
        k = (p.get("createdate") or "")[:7]
        months[k] = months.get(k, 0) + 1
        f = p.get("first_conversion_event_name") or p.get("recent_conversion_event_name") or "Unknown form"
        if f.startswith(LGF):
            f = re.sub(r"^[:\s]+", "", f[len(LGF):])
        forms[f] = forms.get(f, 0) + 1
    return {
        "count": len(leads),
        "withDeal": sum(1 for c in leads if num(c["properties"].get("num_associated_deals")) > 0),
        "months": months,
        "forms": sorted(forms.items(), key=lambda kv: -kv[1]),
    }


# ── Account funnel ────────────────────────────────────────────────────────────

def group_accounts(leads: list):
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def add(x):
        parent.setdefault(x, x)

    def uni(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a

    assigned, unmatched = [], []
    for c in leads:
        p = c["properties"]
        d, n, keys = domain_of(p.get("email")), norm_name(p.get("company")), []
        if d and d not in PERSONAL and not VISME_DOMAIN.search(d):
            keys.append("d:" + d)
        if n and len(n) > 1 and n not in JUNK_CO:
            keys.append("n:" + n)
        if not keys:
            unmatched.append(c)
            continue
        for k in keys:
            add(k)
        for k in keys[1:]:
            uni(keys[0], k)
        assigned.append((c, keys[0]))
    accts = {}
    for c, k in assigned:
        accts.setdefault(find(k), {"contacts": []})["contacts"].append(c)
    for a in accts.values():
        names = {}
        for c in a["contacts"]:
            n = (c["properties"].get("company") or "").strip()
            if n and norm_name(n) not in JUNK_CO:
                names[n] = names.get(n, 0) + 1
        top = max(names.items(), key=lambda kv: kv[1])[0] if names else None
        a["name"] = top or domain_of(a["contacts"][0]["properties"].get("email")) or "Unknown"
    return list(accts.values()), unmatched


def load_lead_deals(leads: list) -> dict:
    """{lead_id: [deal, ...]} — sales-pipeline deals created after the lead."""
    with_deals = [c for c in leads if num(c["properties"].get("num_associated_deals")) > 0]
    assoc = hs.associations("contacts", "deals", [c["id"] for c in with_deals])
    deal_ids = [d for ids in assoc.values() for d in ids]
    deals = {d["id"]: d for d in hs.batch_read("deals", deal_ids, ["dealname", "dealstage", "pipeline", "amount", "createdate"])}
    out = {}
    for c in with_deals:
        created = c["properties"].get("createdate") or ""
        out[c["id"]] = [deals[i] for i in assoc.get(c["id"], []) if i in deals
                        and (deals[i]["properties"].get("pipeline") or "default") in SALES_PIPES
                        and (deals[i]["properties"].get("createdate") or "") >= created]
    return out


def meeting_outcome(m: dict, now_ms: float) -> str:
    t = parse_ms(m["properties"].get("hs_meeting_start_time"))
    o = m["properties"].get("hs_meeting_outcome") or ""
    if o == "SCHEDULED" or o not in OUTCOME_RANK:
        o = "UPCOMING" if t > now_ms else "NOTLOGGED"
    return o


def parse_ms(s) -> float:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return 0.0


def build_funnel(leads: list, best_meeting: dict, deals: dict) -> dict:
    accounts, unmatched = group_accounts(leads)
    out = []
    for a in accounts:
        s, lost, met, held = 0, False, False, False
        for c in a["contacts"]:
            lc = LC_RANK.get(c["properties"].get("lifecyclestage"), -1)
            if lc >= 3:
                s = max(s, 1)
            o = best_meeting.get(c["id"])
            if o is not None:
                met = True
                if o == "COMPLETED":
                    held = True
                s = max(s, 3 if o == "COMPLETED" else 2)
            if lc == 4:
                s = max(s, 4)
            for d in deals.get(c["id"], []):
                st = d["properties"].get("dealstage")
                if st in WON:
                    s = max(s, 5)
                else:
                    s = max(s, 4)
                    if st in LOST:
                        lost = True
        out.append({"name": a["name"], "n": len(a["contacts"]), "step": s,
                    "lost": lost, "met": met, "held": held})
    return {"leads": len(leads), "unmatched": len(unmatched), "accounts": out}


# ── HubSpot: meetings ─────────────────────────────────────────────────────────

def load_meetings(leads: list) -> dict:
    lead_ids = {c["id"] for c in leads}
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    assoc = hs.associations("contacts", "meetings", list(lead_ids))
    meeting_ids = {m for ids in assoc.values() for m in ids}
    props = ["hs_meeting_title", "hs_meeting_start_time", "hs_createdate", "hs_meeting_outcome",
             "hubspot_owner_id", "hs_attendee_owner_ids"]
    meetings = [m for m in hs.batch_read("meetings", list(meeting_ids), props)
                if (m["properties"].get("hs_createdate") or "") >= START_DATE]
    meetings.sort(key=lambda m: m["properties"].get("hs_meeting_start_time") or "", reverse=True)

    m_contacts = hs.associations("meetings", "contacts", [m["id"] for m in meetings])
    contact_ids = {c for ids in m_contacts.values() for c in ids}
    contacts = {c["id"]: c for c in hs.batch_read(
        "contacts", list(contact_ids), ["firstname", "lastname", "jobtitle", "company", "email"])}
    owner_names = hs.owners()

    # meetingBest: best outcome per lead, used by the account funnel
    best = {}
    for m in meetings:
        o = meeting_outcome(m, now_ms)
        for cid in m_contacts.get(m["id"], []):
            if cid in lead_ids and (cid not in best or OUTCOME_RANK[o] > OUTCOME_RANK[best[cid]]):
                best[cid] = o

    rows, upcoming = [], 0
    for m in meetings:
        p = m["properties"]
        t = parse_ms(p.get("hs_meeting_start_time"))
        if t > now_ms:
            upcoming += 1
        label = OUTCOME_LABEL.get(p.get("hs_meeting_outcome") or "") or (["Upcoming", "open"] if t > now_ms else ["Not logged", "sched"])
        cs = [contacts[i] for i in m_contacts.get(m["id"], []) if i in contacts]
        cs.sort(key=lambda c: 0 if c["id"] in lead_ids else 1)
        lead_c = next((c for c in cs if c["id"] in lead_ids), cs[0] if cs else None)
        acct = (lead_c["properties"].get("company") or "") if lead_c else ""
        parts = []
        for c in cs:
            q = c["properties"]
            co = q.get("company") or ""
            parts.append({
                "id": c["id"],
                "name": full_name(q) or "Unnamed contact",  # email deliberately not published
                "sub": ", ".join(x for x in [q.get("jobtitle"), co if co != acct else ""] if x),
                "lead": c["id"] in lead_ids,
            })
        owner_ids = [x.strip() for x in [p.get("hubspot_owner_id") or ""] + str(p.get("hs_attendee_owner_ids") or "").split(";")
                     if x.strip().isdigit()]
        team = [owner_names.get(i) or f"Owner {i}" for i in dict.fromkeys(owner_ids)]
        rows.append({"acct": acct, "parts": parts, "team": team, "title": p.get("hs_meeting_title") or "Untitled meeting",
                     "start": p.get("hs_meeting_start_time"), "outcome": label})
    return {"count": len(meetings), "upcoming": upcoming, "rows": rows, "best": best}


# ── Fibbler: spend, pipeline, deals ───────────────────────────────────────────

def load_fibbler(fib: Fibbler) -> dict:
    base = {"source": "LINKEDIN", "time_period": "custom", "start_month": START_MONTH, "end_month": cur_month()}
    summary = fib.call("get_deal_attribution_summary", base)
    deals = fib.call("get_influenced_deals", {**base, "limit": 200, "sort_by": "amount"}).get("deals") or []
    keep = ["dealName", "stage", "dealType", "amount", "amountCurrency", "paidImpressions",
            "organicImpressions", "createDate"]
    return {
        "sum": {k: summary.get(k) for k in ("totalInfluencedPipeline", "totalInfluencedRevenue",
                                           "wonDealsCount", "currency")},
        "deals": [{k: d.get(k) for k in keep} for d in deals],
    }


def load_spend(fib: Fibbler) -> dict:
    """Rolling 30-day periods from Fibbler's daily-backed windows (calendar months lag)."""
    start = datetime.strptime(START_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    wide = "180d" if (datetime.now(timezone.utc) - start).days <= 178 else "365d"

    def roll(tp):
        return fib.call("get_campaign_performance", {"time_period": tp, "sort_by": "spend", "limit": 1})

    trend = fib.call("get_trend_data", {"metrics": "spend", "months": 12})
    r30, r60, r90, rw = roll("30d"), roll("60d"), roll("90d"), roll(wide)
    sp = lambda r: num((r.get("totals") or {}).get("spend"))
    st = lambda r: (r.get("period") or {}).get("start", "")
    en = lambda r: (r.get("period") or {}).get("end", "")
    day_before = lambda d: (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    w_start_m = st(rw)[:7]
    pre_start = sum(num(m.get("spend")) for m in trend.get("adMetrics") or []
                    if START_MONTH > m["month"] >= w_start_m)
    periods = []
    if START_DATE < st(r90):
        periods.append({"start": START_DATE, "end": day_before(st(r90)),
                        "spend": max(0, sp(rw) - sp(r90) - pre_start)})
    periods.append({"start": st(r90), "end": day_before(st(r60)), "spend": sp(r90) - sp(r60)})
    periods.append({"start": st(r60), "end": day_before(st(r30)), "spend": sp(r60) - sp(r30)})
    periods.append({"start": st(r30), "end": en(r30), "spend": sp(r30)})
    return {"periods": periods, "total": max(0, sp(rw) - pre_start), "last90": sp(r90)}


# ── Dark funnel ───────────────────────────────────────────────────────────────

def linkedin_times(p: dict) -> list:
    t = []
    if is_lgf_event(p.get("first_conversion_event_name")) and p.get("first_conversion_date"):
        t.append(p["first_conversion_date"])
    if is_lgf_event(p.get("recent_conversion_event_name")) and p.get("recent_conversion_date"):
        t.append(p["recent_conversion_date"])
    if (p.get("hs_analytics_source_data_1") or "") == "LinkedIn" and p.get("createdate"):
        t.append(p["createdate"])
    return t


def demo_date_of(p: dict):
    if DEMO_EVENT.search(p.get("first_conversion_event_name") or "") and (p.get("first_conversion_date") or "") >= START_DATE:
        return p["first_conversion_date"]
    if DEMO_EVENT.search(p.get("recent_conversion_event_name") or "") and (p.get("recent_conversion_date") or "") >= START_DATE:
        return p["recent_conversion_date"]
    return None


def load_demo_requests() -> list:
    props = ["firstname", "lastname", "email", "jobtitle", "company", "createdate", "form_filled",
             "first_conversion_event_name", "first_conversion_date", "recent_conversion_event_name",
             "recent_conversion_date", "hs_analytics_source", "hs_analytics_source_data_1",
             "lifecyclestage", "num_associated_deals"]
    forms = {"propertyName": "form_filled", "operator": "IN", "values": DEMO_FORMS}
    return hs.search("contacts", [
        {"filters": [forms, {"propertyName": "first_conversion_date", "operator": "GTE", "value": hs.ms(START_DATE)}]},
        {"filters": [forms, {"propertyName": "recent_conversion_date", "operator": "GTE", "value": hs.ms(START_DATE)}]}],
        props, sorts=[{"propertyName": "createdate", "direction": "ASCENDING"}])


def load_engaged_companies(fib: Fibbler) -> list:
    out, cursor = [], None
    for _ in range(4):
        args = {"time_period": "custom", "start_month": START_MONTH, "end_month": cur_month(),
                "limit": 500, "sort_by": "engagements"}
        if cursor:
            args["cursor"] = cursor
        p = fib.call("get_company_engagement", args)
        out.extend(p.get("companies") or [])
        cursor = p.get("nextCursor")
        if not cursor:
            break
    return out


def build_dark_funnel(fib: Fibbler, leads: list, demos: list, companies: list) -> dict:
    counts, cmap = {}, {}
    for c in companies:
        d = (c.get("domain") or "").lower()
        if d:
            counts[d] = counts.get(d, 0) + 1
            cmap[d] = c
    for d, n in counts.items():
        if n > 1 or d in PERSONAL:
            cmap.pop(d, None)

    def match_co(dom):
        parts = dom.split(".")
        while len(parts) >= 2:
            k = ".".join(parts)
            if k in cmap:
                return cmap[k]
            parts.pop(0)
        return None

    lgf_dom, lgf_name = {}, {}
    for l in leads:
        p = l["properties"]
        t, d, n = p.get("createdate"), domain_of(p.get("email")), norm_name(p.get("company"))
        if d and d not in PERSONAL:
            lgf_dom.setdefault(d, []).append(t)
        if n:
            lgf_name.setdefault(n, []).append(t)

    accts, seen = {}, set()
    for c in demos:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        p = c["properties"]
        dom = domain_of(p.get("email"))
        if not dom or dom in PERSONAL or VISME_DOMAIN.search(dom):
            continue
        demo_at = demo_date_of(p)
        if not demo_at:
            continue
        co = match_co(dom)
        if not co:
            continue
        c["demoAt"] = demo_at
        key = co.get("linkedInPage") or co.get("name")
        a = accts.setdefault(key, {"co": co, "demos": [], "lgf": [], "domains": set()})
        a["demos"].append(c)
        a["domains"].add(dom)
        a["lgf"] += linkedin_times(p) + lgf_dom.get(dom, []) + lgf_name.get(norm_name(p.get("company")), []) \
            + lgf_name.get(norm_name(co.get("name")), [])

    # every contact at the matched domains, to catch older LinkedIn leads
    doms = sorted({d for a in accts.values() for d in a["domains"]})
    dom_li = {}
    for i in range(0, len(doms), 5):
        groups = [{"filters": [{"propertyName": "hs_email_domain", "operator": "EQ", "value": d}]}
                  for d in doms[i:i + 5]]
        for r in hs.search("contacts", groups, ["email", "createdate", "first_conversion_event_name",
                                                "first_conversion_date", "recent_conversion_event_name",
                                                "recent_conversion_date", "hs_analytics_source_data_1"]):
            dom_li.setdefault(domain_of(r["properties"].get("email")), []).extend(linkedin_times(r["properties"]))

    items = []
    for a in accts.values():
        for d in a["domains"]:
            a["lgf"] += dom_li.get(d, [])
        a["demos"].sort(key=lambda x: x["demoAt"])
        a["first_demo"] = a["demos"][0]["demoAt"]
        if any(t and t <= a["first_demo"] for t in a["lgf"]):
            continue  # a LinkedIn lead came in first
        a["later"] = len({t for t in a["lgf"] if t and t > a["first_demo"]})
        a["customer"] = any((d["properties"].get("lifecyclestage") or "") == "customer" for d in a["demos"])
        a["has_deal"] = any(num(d["properties"].get("num_associated_deals")) > 0 for d in a["demos"])
        items.append(a)

    j_start = month_add(START_MONTH, -3)
    for a in items:
        try:
            p = fib.call("get_customer_journey", {"company_name": a["co"]["name"], "start_month": j_start})
            js = p.get("journeys") or []
            j = next((x for x in js if x.get("companyName") == a["co"]["name"]), js[0] if js else None)
            a["timeline"] = (j or {}).get("timeline") or []
            a["fib_deals"] = (j or {}).get("dealEvents") or []
        except Exception as exc:  # one account failing must not sink the dashboard
            print(f"  ⚠️  journey failed for {a['co']['name']}: {exc}")
            a["timeline"], a["fib_deals"] = None, []

    for a in items:
        dm = a["first_demo"][:7]
        eng = imp = same = 0
        first = None
        monthly = {}
        for r in a["timeline"] or []:
            m = (r.get("startDate") or "")[:7]
            e = num(r.get("paidEngagements")) + num(r.get("organicEngagements"))
            im = num(r.get("paidImpressions")) + num(r.get("organicImpressions"))
            monthly[m] = monthly.get(m, 0) + e
            if m < dm:
                eng += e
                imp += im
                if (e or im) and (first is None or m < first):
                    first = m
            elif m == dm:
                same += e
        a.update(eng_before=int(eng), imp_before=int(imp), first_eng=first, eng_same=same, monthly=monthly)

    kept = [a for a in items if a["timeline"] is None or a["eng_before"] > 0 or a["imp_before"] > 0]
    same_month = [a for a in items if a["timeline"] is not None and a["eng_before"] == 0
                  and a["imp_before"] == 0 and a["eng_same"] > 0]
    kept.sort(key=lambda a: (a["customer"], -a["eng_before"], -a["imp_before"]))

    def rec(a):
        dp = a["demos"][0]["properties"]
        return {
            "name": a["co"]["name"],
            "id": a["demos"][0]["id"],
            "who": full_name(dp) or "Unnamed contact",
            "jobtitle": dp.get("jobtitle") or "",
            "moreRequests": len(a["demos"]) - 1,
            "firstDemo": a["first_demo"],
            "form": dp.get("form_filled") or "",
            "via": SRC.get(dp.get("hs_analytics_source"), dp.get("hs_analytics_source") or ""),
            "customer": a["customer"],
            "laterLgf": a["later"],
            "journey": a["timeline"] is not None,
            "impBefore": a["imp_before"],
            "engBefore": a["eng_before"],
            "firstEng": a["first_eng"],
            "monthly": a["monthly"],
            "deal": bool(a["fib_deals"]) or a["has_deal"],
        }

    return {"list": [rec(a) for a in kept],
            "sameMonth": [{"name": a["co"]["name"], "firstDemo": a["first_demo"]} for a in same_month],
            "jStart": j_start}


# ── Build ─────────────────────────────────────────────────────────────────────

def build_payload() -> dict:
    print("=" * 60)
    print("Building performance/index.html (LinkedIn Ads)")
    print("=" * 60)

    fib = Fibbler()

    print("\n[1/7] Leads…")
    leads = load_leads()
    print(f"  {len(leads)} lead gen form leads")

    print("[2/7] Deals attached to leads…")
    deals = load_lead_deals(leads)

    print("[3/7] Meetings…")
    meetings = load_meetings(leads)
    print(f"  {meetings['count']} meetings")

    print("[4/7] Fibbler pipeline and deals…")
    fibbler = load_fibbler(fib)

    print("[5/7] Fibbler spend periods…")
    spend = load_spend(fib)

    print("[6/7] Demo requests and engaged companies…")
    demos = load_demo_requests()
    companies = load_engaged_companies(fib)
    print(f"  {len(demos)} demo contacts, {len(companies)} engaged companies")

    print("[7/7] Dark funnel…")
    dark = build_dark_funnel(fib, leads, demos, companies)
    print(f"  {len(dark['list'])} accounts")

    funnel = build_funnel(leads, meetings.pop("best"), deals)
    return {
        "lastUpdated": date.today().isoformat(),
        "startDate": START_DATE,
        "startMonth": START_MONTH,
        "urlTemplate": hs.contact_url_template(),
        "leads": lead_summary(leads),
        "funnel": funnel,
        "meetings": meetings,
        "spend": spend,
        "fibbler": fibbler,
        "dark": dark,
    }


def main():
    try:
        data = build_payload()
    except EnvironmentError as exc:
        print(f"\n❌  Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌  Build failed: {exc}", file=sys.stderr)
        raise
    inject_data(template_path=TEMPLATE, data_dict={"LI": data}, output_path=OUTPUT)
    print("Done.")


if __name__ == "__main__":
    main()

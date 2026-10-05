#!/usr/bin/env python3
"""
Offline check for build_performance.py: mocks HubSpot + Fibbler, runs build_payload(),
asserts the account funnel, meetings and dark-funnel rules.
    python scripts/test_build_performance.py [out.html]   (writes a rendered preview if given)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.build_performance as bp
from scripts.shared.html_utils import inject_data

LGF = "LinkedIn Lead Generation Ad: Sponsorship Personas"


def contact(i, email, company, **p):
    return {"id": str(i), "properties": {"email": email, "company": company, "firstname": f"F{i}",
                                         "lastname": "L", "createdate": "2026-06-10T10:00:00Z", **p}}


LEADS = [
    contact(1, "a@acme.com", "Acme", first_conversion_event_name=LGF, lifecyclestage="salesqualifiedlead", num_associated_deals="1"),
    contact(2, "b@acme.com", "Acme Inc", first_conversion_event_name=LGF, lifecyclestage="lead"),
    contact(3, "c@gmail.com", "", first_conversion_event_name=LGF),               # unmatched
    contact(4, "t@visme.co", "Visme", first_conversion_event_name=LGF),           # internal test, dropped
]
DEMOS = [
    contact(10, "d@sportfive.com", "SPORTFIVE", form_filled="Main Sales Form - Site",
            first_conversion_event_name="Talk to Sales - Main Sales Form", first_conversion_date="2026-09-15T10:00:00Z",
            hs_analytics_source="PAID_SEARCH", lifecyclestage="lead"),
    contact(11, "e@learfield.com", "Learfield", form_filled="Main Sales Form - Site",       # LinkedIn lead first -> excluded
            first_conversion_event_name="Talk to Sales - Main Sales Form", first_conversion_date="2026-09-20T10:00:00Z"),
]
COMPANIES = [{"name": "SPORTFIVE", "domain": "sportfive.com", "linkedInPage": "li/sportfive"},
             {"name": "LEARFIELD", "domain": "learfield.com", "linkedInPage": "li/learfield"}]
JOURNEY = {"journeys": [{"companyName": "SPORTFIVE", "timeline": [
    {"startDate": "2026-07-01", "paidImpressions": 900, "paidEngagements": 30},
    {"startDate": "2026-09-01", "paidImpressions": 100, "paidEngagements": 5}], "dealEvents": []}]}


class FakeFib:
    def call(self, tool, args):
        if tool == "get_company_engagement":
            return {"companies": COMPANIES}
        if tool == "get_customer_journey":
            return JOURNEY
        if tool == "get_deal_attribution_summary":
            return {"totalInfluencedPipeline": 1000, "totalInfluencedRevenue": 500, "wonDealsCount": 1, "currency": "USD"}
        if tool == "get_influenced_deals":
            return {"deals": [{"dealName": "D1", "stage": "Proposal Sent", "amount": 1000, "createDate": "2026-08-01T00:00:00Z"},
                              {"dealName": "D2", "stage": "Closed Won", "amount": 500, "createDate": "2026-07-01T00:00:00Z"}]}
        if tool == "get_trend_data":
            return {"adMetrics": [{"month": "2026-05", "spend": 0}]}
        if tool == "get_campaign_performance":
            days = {"30d": 30, "60d": 60, "90d": 90}.get(args["time_period"], 180)
            return {"period": {"start": f"2026-{'06' if days > 90 else '07'}-0{1 + days % 7}", "end": "2026-10-05"},
                    "totals": {"spend": days * 100}}
        raise AssertionError(tool)


def fake_search(obj, groups, props, sorts=None, max_pages=50):
    flat = str(groups)
    if "hs_email_domain" in flat:
        return [contact(11, "x@learfield.com", "Learfield", first_conversion_event_name=LGF,
                        first_conversion_date="2026-09-01T00:00:00Z")]
    if "form_filled" in flat:
        return DEMOS
    return LEADS + [LEADS[3]]


bp.Fibbler = FakeFib
bp.hs.search = fake_search
bp.hs.associations = lambda f, t, ids: {
    ("contacts", "deals"): {"1": ["d1"]}, ("contacts", "meetings"): {"1": ["m1"]},
    ("meetings", "contacts"): {"m1": ["1", "99"]}}[(f, t)]
bp.hs.batch_read = lambda t, ids, props: {
    "deals": [{"id": "d1", "properties": {"dealstage": "closedwon", "pipeline": "default", "createdate": "2026-07-01T00:00:00Z"}}],
    "meetings": [{"id": "m1", "properties": {"hs_meeting_title": "Intro", "hs_meeting_start_time": "2026-07-02T15:00:00Z",
                                             "hs_createdate": "2026-06-20T00:00:00Z", "hs_meeting_outcome": "COMPLETED",
                                             "hubspot_owner_id": "7", "hs_attendee_owner_ids": ""}}],
    "contacts": [LEADS[0], contact(99, "z@acme.com", "Acme", jobtitle="VP")]}[t]
bp.hs.owners = lambda: {"7": "Sam Rep"}
bp.hs.contact_url_template = lambda: "https://app.hubspot.com/contacts/1/record/0-1/{id}"

if __name__ == "__main__":
    d = bp.build_payload()
    assert d["leads"]["count"] == 3, d["leads"]                    # test submission dropped
    f = d["funnel"]
    assert len(f["accounts"]) == 1 and f["accounts"][0]["n"] == 2 and f["unmatched"] == 1, f   # Acme + Acme Inc merge
    assert f["accounts"][0]["step"] == 5 and f["accounts"][0]["held"], f                         # won deal beats meeting
    assert d["meetings"]["count"] == 1 and d["meetings"]["rows"][0]["team"] == ["Sam Rep"]
    assert [p["lead"] for p in d["meetings"]["rows"][0]["parts"]] == [True, False]
    assert [a["name"] for a in d["dark"]["list"]] == ["SPORTFIVE"], d["dark"]                    # Learfield excluded
    assert d["dark"]["list"][0]["engBefore"] == 30 and d["dark"]["list"][0]["impBefore"] == 900
    assert "email" not in str(d["meetings"]) and "@" not in str(d["dark"])                       # no emails published
    print("OK")
    if len(sys.argv) > 1:
        inject_data(bp.TEMPLATE, {"LI": d}, sys.argv[1])

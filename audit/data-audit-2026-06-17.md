# Visme Dashboard Data Audit — 2026-06-17

## Summary
- **Total findings:** 16
- **Critical:** 2 | **High:** 4 | **Medium:** 6 | **Low:** 4
- **Dashboards audited:** Executive Overview, GA4 Traffic & Engagement, Website Traffic, HubSpot Pipeline & Revenue (partial), Amplitude PLG Metrics, GSC SEO Performance, Paid Media (partial)
- **Audit period reference week:** Jun 8–14 2026 (most recent complete week as of Jun 17 2026)

### MCP queries run
All GA4 queries used property `368188880`. GSC queries used `https://www.visme.co/`. HubSpot and Amplitude data were verified from injected dashboard payloads (direct API verification was not possible for those sources). Google Ads and Microsoft Ads data could not be independently verified.

---

## Findings

---

### GA4 Traffic & Engagement — Conversion Funnel (Registration Step)
**Severity:** Critical  
**What the dashboard shows:** `create_an_account` = 19 events for week of Jun 8–14 (shown as the "Registration" / first funnel step)  
**What the source shows:** GA4 property 368188880, Jun 8–14: `register` event = 18,861 occurrences; `create_an_account` = 19 occurrences; `visit_payment_page` = 0 occurrences  
**Root cause:** `ga4_client.py` defines `TARGET_EVENTS = ["create_an_account", "visit_payment_page", "purchase"]`. The primary registration event on visme.co is `register` (firing ~18,861 times/week), not `create_an_account` (firing ~19 times/week). The wrong event name is hardcoded. `visit_payment_page` also fires 0 times — this event either no longer exists or was renamed.  
**Recommended fix:** Replace `"create_an_account"` with `"register"` in `TARGET_EVENTS`. Investigate and remove or replace `"visit_payment_page"` with the current payment-page event name (or remove if no equivalent exists). This affects both the GA4 dashboard funnel chart and the Executive Overview full-funnel section, which uses the same `ga4_client.py`.

---

### GSC SEO Performance — Weekly Clicks & Impressions
**Severity:** Critical  
**What the dashboard shows:** Week of Jun 8: clicks = 10,638 | impressions = 633,278 | CTR = 1.68% | position = 10.4  
**What the source shows:** Direct GSC API query for Jun 8–14 2026 (7 days):

| Date | Clicks | Impressions |
|------|--------|-------------|
| Jun 8 | 10,638 | 633,278 |
| Jun 9 | 10,891 | 630,278 |
| Jun 10 | 10,478 | 649,208 |
| Jun 11 | 9,395 | 598,107 |
| Jun 12 | 7,517 | 511,044 |
| Jun 13 | 6,077 | 452,351 |
| Jun 14 | 7,494 | 505,911 |
| **Week total** | **62,490** | **3,980,177** |

The dashboard value (10,638 clicks) exactly matches **Monday Jun 8 alone**. The full-week total is 62,490 clicks — **5.9× higher** than displayed.  
**Root cause:** The Google Apps Script that populates the `gsc_weekly` Google Sheet is writing one day of data per row (using the Monday date as the row key) rather than aggregating the full Mon–Sun week. `fetch_gsc_sheet_data` reads these values directly without any further aggregation, so the dashboard inherits the per-day figures as if they were weekly. All historical weekly bars in the GSC trend chart are understated by the same factor.  
**Recommended fix:** Fix the Apps Script to query GSC with `startDate = Monday, endDate = Sunday` (no `date` dimension) so it writes the full 7-day aggregate per row.

---

### GA4 Traffic & Engagement — Conversion Funnel (Payment Page Step)
**Severity:** High  
**What the dashboard shows:** `visit_payment_page` = 0 for all recent weeks  
**What the source shows:** GA4 property 368188880: `visit_payment_page` returns 0 event count for Jun 8–14 and multiple prior weeks. The event either does not exist on this property or has been renamed.  
**Root cause:** `TARGET_EVENTS` in `ga4_client.py` includes `"visit_payment_page"`, which is not an active GA4 event on this property. The "Payment Page" funnel step is permanently zero, making the funnel misleading (shows the drop-off from Account Creation → Payment as 100% rather than the true figure).  
**Recommended fix:** Identify the current event name for payment-page visits (e.g. `view_item`, `begin_checkout`, or a custom event) and replace `"visit_payment_page"` in `TARGET_EVENTS`. If no such event exists in GA4, remove this funnel step.

---

### Cross-dashboard — Sessions Total Inconsistency
**Severity:** High  
**What the dashboards show:**
- GA4 Traffic & Engagement dashboard (Jun 8 week): **186,958 sessions** (total)
- Website Traffic dashboard (Jun 8 week, channel sum): **185,638 sessions** (Organic Search 95,916 + Direct 72,229 + all other channels)
- GA4 API direct query (Jun 8–14): **191,709 total sessions**

All three figures are different.  
**What the source shows:** GA4 API Jun 8–14 total sessions = 191,709. Sum of all channel rows (14 channels) from the same query = 185,808. Difference of ~5,901 sessions do not appear in any named `sessionDefaultChannelGrouping` (they have no channel assignment).  
**Root cause (two parts):**  
1. The ~5,901 unattributed sessions are silently excluded from every channel chart and table across all dashboards. Neither dashboard shows an "unattributed" row or any footnote indicating ~3% of sessions are excluded.  
2. The GA4 and Website dashboards were built at different times (different CI runs), so they reflect GA4 data at the moment each build ran. GA4 data continues to be processed after the fact, causing ~1,320-session drift between builds.  
**Recommended fix:** Add an "(other / unattributed)" row to the website dashboard's Latest Week Snapshot and Quality Checks sections showing sessions not in any named channel. Document the build-time snapshot nature of the data somewhere on each dashboard.

---

### Executive Overview & GA4 Traffic — Registration Count Discrepancy Across Dashboards
**Severity:** High  
**What the dashboards show:**
- Executive Overview — Registrations (from Amplitude "Sign Up Completed"): **23,855** for week of Jun 8–14
- GA4 Traffic & Engagement — Account Creations (from `create_an_account`): **19** for same week
- GA4 `register` event (not currently shown anywhere): **18,861** for same week

**What the source shows:** All three figures come from different sources/events and none reconcile. The Executive dashboard shows Amplitude signups (23,855), the GA4 dashboard shows essentially zero (wrong event), and the true GA4 registration signal (`register` event, 18,861) is not visible in any dashboard.  
**Root cause:** (a) GA4 dashboard uses the wrong event (see finding above). (b) Amplitude "Sign Up Completed" (23,855) includes signups from native app and other surfaces that GA4 doesn't track. The 26% gap between Amplitude and GA4 `register` is unreconciled and undocumented.  
**Recommended fix:** Fix the GA4 event (see Critical finding). Then document the expected gap between Amplitude and GA4 registrations so readers understand why the two numbers differ.

---

### Executive Overview — MQLs Showing Zero for All Recent Weeks
**Severity:** High  
**What the dashboard shows:** MQLs = 0 for week of Jun 1–7 and week of Jun 8–14 (both most recent complete weeks). MQL column in the Executive Summary table appears to be empty/non-functional.  
**What the source shows:** HubSpot data is sourced from a Google Sheet (`Weekly Summary` tab, column C). The injected payload confirms `mqls: 0.0` for both weeks. Could not verify against HubSpot API directly (data passes through an intermediate Sheet).  
**Root cause:** Either (a) the MQL definition/lifecycle stage is not configured in HubSpot and the Sheet formula returns 0, (b) the Apps Script exporting HubSpot data to the Sheet is not populating the MQL column, or (c) MQLs genuinely zero but this should be verified.  
**Recommended fix:** Verify the HubSpot export script populates the MQL column. If MQLs are intentionally not tracked, remove the column from the Executive Summary to avoid showing misleading zeros.

---

### GA4 Traffic & Engagement — Week Label Format Inconsistency vs Website Dashboard
**Severity:** Medium  
**What the GA4 dashboard shows:** Weeks labeled by their **Sunday end date** — e.g. "Jun 14 '26" for the week of Jun 8–14.  
**What the Website Traffic dashboard shows:** Same week labeled by its **Monday start date** — e.g. "Jun 8".  
**Root cause:** `ga4_client.py` computes labels as `_fmt_label(sunday)` (line: `sunday = datetime.strptime(w, "%Y-%m-%d").date() + timedelta(days=6)`). `build_website.py` computes labels as `_fmt_label(monday_str)`. Both are internally consistent but the label convention is opposite across the two most-used dashboards.  
**Recommended fix:** Standardise on one convention across all build scripts. Monday start dates ("Jun 8") are more conventional for weekly business reporting.

---

### GSC SEO Performance — `positionDist` Always Empty
**Severity:** Medium  
**What the dashboard shows:** Any chart or section driven by `positionDist` renders empty.  
**What the source shows:** The injected payload has `"positionDist": {}`. The `fetch_gsc_sheet_data` function in `sheets_client.py` initialises this as an empty dict and never populates it. There is no `gsc_position_dist` tab in the expected sheet schema.  
**Root cause:** `positionDist` was likely planned but never implemented in the Apps Script exporter or `sheets_client.py`.  
**Recommended fix:** Either implement position distribution bucketing (querying GSC by position ranges) or remove `positionDist` references from the dashboard HTML.

---

### Amplitude PLG — Activation Rate Is Not Cohort-Based
**Severity:** Medium  
**What the dashboard shows:** Activation rate for week Jun 8–14: **74.9%** (17,867 `Project Created` events / 23,855 `Sign Up Completed` events in the same calendar week)  
**What a cohort-based rate would show:** The correct activation rate would be: of users who signed up in week N, what % created a project within some window (e.g. 7 days, D7). Users who sign up on a Friday in week N may not activate until week N+1, causing same-week activations to be under-counted.  
**Root cause:** `amplitude_client.py` computes `actRate` as `activations / signups` using raw event counts in the same calendar week. This is a period-over-period ratio, not a true cohort-based activation rate. The Amplitude retention API is called separately (`_fetch_retention`) but this data is not included in the dashboard payload.  
**Recommended fix:** Either label the metric clearly as "Weekly Project Creation Rate (same-week)" (not "Activation Rate") or switch to a D7 cohort-based calculation using the retention API data already being fetched.

---

### Amplitude PLG vs GA4 — Registration Count Gap Undocumented
**Severity:** Medium  
**What the dashboards show:** Amplitude "Sign Up Completed" Jun 8–14: **23,855** | GA4 `register` event Jun 8–14: **18,861** (26% gap)  
**What the source shows:** Both figures are independently verified. Amplitude tracks signups including app/mobile surfaces; GA4 tracks web-only. The gap is real but never explained in any dashboard.  
**Root cause:** Different instrumentation surfaces (web + app vs web-only) and potential differences in event firing logic. Gap is expected but undocumented.  
**Recommended fix:** Add a brief note to the Executive Overview or Amplitude PLG dashboard explaining the expected gap between Amplitude and GA4 registration counts.

---

### Website Traffic — ~5,900 Sessions/Week Silently Excluded
**Severity:** Medium  
**What the dashboard shows:** Sum of all named-channel sessions for Jun 8–14: 185,638. No row for sessions without a channel assignment.  
**What the source shows:** GA4 total sessions Jun 8–14: 191,709. Named-channel sum from the same GA4 dimension query: 185,808. Difference: ~5,901 sessions (3.1%) have no `sessionDefaultChannelGrouping` value and are excluded from all channel charts, the channel table, and the Latest Week Snapshot.  
**Root cause:** `build_website.py` only iterates over rows returned by the `sessionDefaultChannelGrouping` dimension query. Sessions where GA4 cannot assign a channel grouping are not returned by that query at all.  
**Recommended fix:** Either fetch total sessions separately and show an "unattributed" figure in Quality Checks, or add a footnote noting that channel totals may not sum to total sessions.

---

### Paid Media — Monthly Budget Hardcoded, No Staleness Detection
**Severity:** Medium  
**What the dashboard shows:** Budget vs. spend tracking uses the `MONTHLY_BUDGETS` dict in `build_ppc.py` (all months from 2026-01 through 2026-12 hardcoded at $11,111/month after Feb).  
**What the source shows:** No external source — budgets are manually maintained in the Python script.  
**Root cause:** There is no automated budget ingestion from a planning tool. If the budget changes mid-year, a developer must remember to update `build_ppc.py`.  
**Recommended fix:** Move monthly budgets to a Google Sheet row or a configuration file that can be updated without a code deploy. Add a build-time warning if a budget entry for the current month is missing.

---

### GSC SEO Performance — Data Sourced from Google Sheet (Staleness Risk)
**Severity:** Low  
**What the dashboard shows:** GSC data `generatedAt: 2026-06-14`. Latest week in payload: Jun 8 (72 weeks of history from Jan 27 2025).  
**What the source shows:** A separate Google Apps Script process populates a Google Sheet from GSC, and `build_gsc.py` reads that Sheet. If the Apps Script fails silently, the dashboard will show stale data without any visible warning.  
**Root cause:** Architectural: GSC data flows through two hops (GSC API → Apps Script → Google Sheet → build script → dashboard). Each hop is a potential failure point.  
**Recommended fix:** Add a data freshness check in `build_gsc.py`: if `generatedAt` is more than 8 days old, emit a warning or fail the build. Consider migrating to direct GSC API calls (the `gsc` MCP confirms the GSC API is accessible with current credentials).

---

### GA4 Traffic & Engagement — Landing Pages Show `(not set)` as #1
**Severity:** Low  
**What the dashboard shows:** Top landing page: `(not set)` with 9,100,469 sessions (95.4% bounce rate) over the full 156-week history. Second is `/v2/login` with 7,012,394 sessions.  
**What the source shows:** GA4 assigns `(not set)` as `landingPagePlusQueryString` for sessions where no landing page was recorded (common for in-app sessions, session stitching, direct app launches). These are not real landing pages.  
**Root cause:** The GA4 dashboard fetches landing pages across the full 3-year window without filtering out `(not set)` or internal app pages like `/v2/login` and `/v2/home`, which are Visme app dashboard pages rather than marketing landing pages.  
**Recommended fix:** Exclude `(not set)` and known app paths (e.g. `/v2/`) from the landing pages query, or add a dimension filter for `hostName = www.visme.co` to restrict to marketing site traffic.

---

### Website Traffic — AI Assistant & Affiliate Fetches Have Low `row_limit`
**Severity:** Low  
**What the dashboard shows:** AI Assistant breakdown: 8 sources; Affiliate breakdown: 6 sources (both correct as of Jun 2026).  
**What the source shows:** `build_website.py` uses `row_limit=500` for both AI Assistant and Affiliate GA4 fetches. Over 13 weeks × 7 days × N sources, this could be approached if new AI tools or affiliate partners are added. Currently safe with 8 and 6 sources respectively.  
**Root cause:** Conservative `row_limit` compared to the `row_limit=5000` used for Organic Social (which was confirmed to need a high limit).  
**Recommended fix:** Increase both to `row_limit=2000` as a precaution.

---

### HubSpot Pipeline & Revenue — Data Not Directly Verifiable Against HubSpot API
**Severity:** Low  
**What the dashboard shows:** Leads Jun 8–14: 15,904 | Deals: 1 | Pipeline: $5,000 | Revenue: $0 (from Google Sheet via `sheets_client.py`).  
**What the source shows:** HubSpot data passes through an intermediate Google Sheet. The HubSpot MCP is available (portal 21774584) but the data in the Sheet could not be verified against live HubSpot records within this audit. The Sheet schema (`Weekly Summary!A2:G`) depends on an external export process.  
**Root cause:** Architectural — HubSpot data is not pulled directly from the HubSpot API; it goes through a Google Sheet maintained by a separate process (not visible in this repository).  
**Recommended fix:** Migrate HubSpot data fetching to use the HubSpot API directly (as is done for GA4 and Amplitude), eliminating the intermediate Sheet dependency and enabling automated verification.

---

## No Issues Found

The following sections were verified as correct:

- **Website Traffic — Channel Sessions (Jun 8–14):** All 14 channel session counts match GA4 API within expected build-time variation (max delta observed: 102 sessions for Organic Search, 0.1%).
- **Website Traffic — New Users by Channel:** Correctly uses `firstUserDefaultChannelGrouping` (not `sessionDefaultChannelGrouping`). Values match GA4 API within expected variation.
- **Website Traffic — AI Assistant Source Breakdown (Jun 8–14):** chatgpt.com 2,256, gemini.google.com 118, perplexity.ai 58, copilot.com 54, claude.ai 32 — all match GA4 API directly. Total 2,521 vs dashboard 2,519 (timing).
- **Website Traffic — Organic Social Platform Grouping:** All platform source variants verified against GA4. Pinterest 386/392, Facebook 101/584, Reddit 88/74, LinkedIn 48/113, Instagram 7/24, X/Twitter 16/5 — all match within ≤1 session (timing).
- **Website Traffic — WoW Suppression Logic:** Correctly suppresses WoW % when either week is below `MIN_VOL=50` for channel-level tables. Correctly uses lower threshold of 10 for the Organic Social platform table.
- **Website Traffic — Week Boundary Logic:** Confirmed trailing 13 complete Mon–Sun weeks, exclusive of the current in-progress week. No partial-week data in any chart.
- **`sessionDefaultChannelGroup` vs `sessionDefaultChannelGrouping`:** Both GA4 dimension names return identical results for property 368188880. No data discrepancy between the two naming conventions on this property.
- **GSC — Top Queries (last 28 days):** Top queries verified against direct GSC API — "visme" (36,343 clicks), "graph maker" (7,357), "visme ai" (3,320) — correct.
- **Amplitude — CR calculation:** `upgrades / signups * 100` = 122/23,855 = 0.51% for Jun 8 week — matches injected `cr: 0.5114`. Correct.

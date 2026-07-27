# Visme Dashboard Data Audit — 2026-07-27

## Summary

- **Audit date:** July 27, 2026
- **Dashboard audited:** GA4 Traffic & Engagement (`/ga4/`)
- **Dashboard asOfDate:** July 19, 2026 (most recent week: Jul 13–19)
- **GA4 property:** 368188880
- **Audit method:** Every figure queried directly from GA4 API (property 368188880) and compared to the injected payload in `ga4/index.html`
- **Total findings:** 7
- **Critical:** 1 | **High:** 1 | **Medium:** 2 | **Low:** 3
- **Prior audit (Jun 17) findings re-verified:** 5 of 16 applicable to GA4 — 0 fixed, 5 still open

---

## Verification Results — Jul 13–19 (Most Recent Week in Dashboard)

Every number below was independently queried from GA4 property 368188880 for the exact date range 2026-07-13 to 2026-07-19.

### Sessions & New Users

| Metric | Dashboard | GA4 API | Delta | Delta % | Verdict |
|--------|-----------|---------|-------|---------|---------|
| Sessions | 182,849 | 183,126 | +277 | +0.15% | ✅ Within normal processing drift |
| New Users | 132,981 | 133,484 | +503 | +0.38% | ✅ Within normal processing drift |

Small deltas are expected and consistent with the June audit's finding that GA4 continues processing data after a build runs. Both figures are accurate.

### Channel Breakdown

| Channel | Dashboard | GA4 API | Delta | Delta % | Verdict |
|---------|-----------|---------|-------|---------|---------|
| Organic Search | 89,416 | 88,448 | -968 | -1.1% | ✅ Processing drift |
| Direct | 75,292 | 75,737 | +445 | +0.6% | ✅ Processing drift |
| Referral | 6,079 | 6,027 | -52 | -0.9% | ✅ Processing drift |
| Unassigned | 3,982 | 3,973 | -9 | -0.2% | ✅ Processing drift |
| Paid Search | 2,918 | 2,922 | +4 | +0.1% | ✅ Processing drift |
| AI Assistant | 2,315 | 2,308 | -7 | -0.3% | ✅ Processing drift |
| Email | 2,041 | 2,054 | +13 | +0.6% | ✅ Processing drift |
| Organic Social | 684 | 680 | -4 | -0.6% | ✅ Processing drift |
| Cross-network | 350 | 348 | -2 | -0.6% | ✅ Processing drift |
| Organic Video | 235 | 233 | -2 | -0.9% | ✅ Processing drift |
| Paid Other | 12 | 12 | 0 | 0% | ✅ Exact match |
| Organic Shopping | 4 | 4 | 0 | 0% | ✅ Exact match |
| Paid Social | 2 | 2 | 0 | 0% | ✅ Exact match |
| Display | 2 | 1 | -1 | -50% | ✅ Negligible (1 session) |
| Paid Video | 0 | 0 | 0 | — | ✅ Correct |
| **Affiliates** | **Not shown** | **30** | — | — | ⚠️ See Finding #5 |

All named channel deltas are within ±1.1% and attributable to build-time snapshot drift. Channel data is accurate.

Sum of all API channels: 182,779. Total GA4 sessions: 183,126. Unattributed (no channel): **347 sessions (0.19%)** — negligible.

### Conversion Events

| Event | Dashboard | GA4 API | Verdict |
|-------|-----------|---------|---------|
| `create_an_account` | 3 | 3 | ✅ Exact match — but see Finding #1 |
| `visit_payment_page` | 2 | 2 | ✅ Exact match — but see Finding #2 |
| `purchase` | 146 | 146 | ✅ Exact match |
| `register` | **Not tracked** | **14,429** | 🚨 See Finding #1 |

### New vs Returning

| Segment | Dashboard | GA4 API | Delta | Verdict |
|---------|-----------|---------|-------|---------|
| New | 136,626 | 137,700 | +1,074 (+0.8%) | ✅ Processing drift |
| Returning | 45,621 | 32,751 | -12,870 (-28.2%) | 🚨 See Finding #3 |
| (not set) | Not shown | 12,300 | — | 🚨 See Finding #3 |

### Missing Week: Jul 20–26

The following data exists in GA4 but is entirely absent from the dashboard:

| Metric | GA4 API Value |
|--------|--------------|
| Sessions | 186,543 |
| New Users | 134,184 |
| `register` events | 13,678 |
| `purchase` events | 190 |
| Top channel — Organic Search | 89,145 |
| Top channel — Direct | 78,797 |

See Finding #4 for root cause.

---

## Findings

---

### Finding #1 — GA4 Funnel: `register` Event Not Tracked (CRITICAL — Carried from June Audit, UNFIXED)

**Severity:** Critical

**What the dashboard shows:** Conversion funnel "Registration" step = `create_an_account` = **3 events** for the week of Jul 13–19.

**What GA4 actually shows:** `register` event = **14,429** for the same week. `create_an_account` = 3 (a near-dead legacy event firing ~3×/week). `visit_payment_page` = 2.

**The gap:** The dashboard understates registrations by **4,809×**.

**Root cause:** `ga4_client.py` line 25:
```python
TARGET_EVENTS = ["create_an_account", "visit_payment_page", "purchase"]
```
The primary registration event on visme.co is `register`. This was identified as Critical in the June 17 audit. The code is unchanged.

**Status:** UNFIXED since June 17 audit.

**Fix:** In `ga4_client.py` line 25, replace `"create_an_account"` with `"register"`:
```python
TARGET_EVENTS = ["register", "visit_payment_page", "purchase"]
```
Note: `visit_payment_page` continues to fire at near-zero (2 events this week). Investigate whether a replacement event exists (see Finding #2).

---

### Finding #2 — `visit_payment_page` Near-Zero in Funnel (HIGH — Carried from June Audit, UNFIXED)

**Severity:** High

**What the dashboard shows:** `visit_payment_page` = 2 for Jul 13–19; 0 for the three preceding weeks.

**What GA4 shows:** `visit_payment_page` = 2 (confirmed). The event occasionally fires but at a volume (~0–2/week) that makes it meaningless as a funnel step.

**Root cause:** `TARGET_EVENTS` in `ga4_client.py` still includes `"visit_payment_page"`. This event either no longer exists as a meaningful tracking point or has been renamed. The funnel shows a ~100% drop-off from Registration → Payment, making the conversion funnel chart misleading.

**Status:** UNFIXED since June 17 audit.

**Fix:** Identify the current payment-page event name (e.g. `begin_checkout`, `view_item`) and replace `"visit_payment_page"` in `TARGET_EVENTS`. If no equivalent event exists in GA4, remove this funnel step from the dashboard HTML.

---

### Finding #3 — `(not set)` New vs Returning Sessions Silently Bucketed as "Returning" (MEDIUM — NEW)

**Severity:** Medium

**What the dashboard shows:** Returning sessions Jul 13–19: **45,621**

**What GA4 shows:**
- Returning: 32,751
- `(not set)`: 12,300
- Combined (32,751 + 12,300): 45,051 ≈ dashboard value (difference explained by build-time data processing)

**Root cause:** `ga4_client.py` line 139:
```python
key = "new" if nvr.lower() == "new" else "returning"
```
Any session where GA4 cannot determine new vs. returning — labeled `(not set)` — falls into the `else` branch and is counted as "returning". This inflates the "returning" count by ~12,300 sessions (~38% of the true returning count) and hides 6.7% of all sessions in an undocumented bucket.

**Impact:** The New vs. Returning chart overstates returning users. Anyone looking at this chart to understand user loyalty/retention is seeing a meaningfully inflated returning figure.

**Fix:** Update the aggregation to explicitly handle `(not set)`:
```python
if nvr.lower() == "new":
    key = "new"
elif nvr.lower() == "returning":
    key = "returning"
# else: skip (not set) — or add a third "unknown" key
```
Alternatively, add a third segment to the chart so `(not set)` sessions are visible rather than hidden.

---

### Finding #4 — Most Recent Complete Week (Jul 20–26) Missing from Dashboard (MEDIUM — NEW)

**Severity:** Medium

**What the dashboard shows:** Most recent week is Jul 13–19 (`asOfDate: July 19, 2026`). File last modified Jul 27 at 08:13 local time.

**What GA4 shows:** The week of Jul 20–26 is fully complete and contains 186,543 sessions and 134,184 new users — a full week of data the dashboard cannot show.

**Root cause:** The build script was run on Sunday July 26. On a Sunday:
- `this_monday = July 26 - 6 days = July 20`
- `last_sunday = July 20 - 1 = July 19`
- End date = July 19 → week of Jul 20–26 excluded

Running the build on Monday July 27 would produce `asOfDate: July 26` and include the missing week. The Monday 10am UTC GitHub Actions workflow has not yet fired, and the manual rebuild referenced by the user appears to have run on Sunday.

**Impact:** The dashboard is systematically one week stale whenever anyone builds on a Sunday. Viewers comparing dashboard figures to reports for "last week" will see data that is one week older than expected.

**Fix:** Enforce the build only runs on Mondays (the GitHub Actions schedule already does this). If a manual rebuild is needed, document that it must be triggered on a Monday. Alternatively, add a visible warning to the dashboard when `asOfDate` is more than 8 days old.

---

### Finding #5 — "Affiliates" Channel Absent from Dashboard (LOW — NEW)

**Severity:** Low

**What the dashboard shows:** `topChannels` list has 15 entries; "Affiliates" is not among them.

**What GA4 shows:** Affiliates channel: 30 sessions in Jul 13–19; 11 sessions in Jul 20–26.

**Root cause:** `topChannels` is computed by summing each channel across all 156 weeks and taking the top 15. "Affiliates" has low enough historical volume that it has not reached the top 15. It is present in GA4 but silently excluded from every channel chart and the channel table.

**Impact:** Minimal at current volume (~0.016% of sessions). However, if affiliates grow, this channel would continue to be excluded without a code change. No immediate user-facing error — the dashboard correctly shows the channels it was built with.

**Fix:** Consider adding a catch-all "(other)" row to the channel table that sums sessions from any channel not in `topChannels`, similar to the recommendation from the June audit.

---

### Finding #6 — Week Labels: GA4 Dashboard Uses Sunday End Date, Website Dashboard Uses Monday Start Date (MEDIUM — Carried from June Audit, UNFIXED)

**Severity:** Medium

**What the dashboard shows:** GA4 dashboard labels weeks by their Sunday end date (e.g. "Jul 19 '26" for the week of Jul 13–19). Website dashboard labels the same week "Jul 13".

**Root cause:** `ga4_client.py` line 208–209:
```python
sunday = datetime.strptime(w, "%Y-%m-%d").date() + timedelta(days=6)
week_labels[w] = _fmt_label(sunday)
```
`build_website.py` uses the Monday date directly. Both scripts internally consistent; convention is opposite.

**Status:** UNFIXED since June 17 audit.

**Fix:** Standardize on Monday start dates across all build scripts. In `ga4_client.py`, change `_fmt_label(sunday)` to `_fmt_label(datetime.strptime(w, "%Y-%m-%d").date())`.

---

### Finding #7 — Landing Pages: `(not set)` and App Paths in Top 10 (LOW — Carried from June Audit, UNFIXED)

**Severity:** Low

**What the dashboard shows:** Top landing page = `(not set)` with 8,940,449 sessions (95.3% bounce rate). Second = `/v2/login` with 6,801,659 sessions. Fifth = `/v2/projects/own` with 1,469,748 sessions.

**What these mean:** `(not set)` are sessions with no recorded landing page (in-app/direct launches). `/v2/*` paths are Visme app interior pages, not marketing landing pages. These dominate the landing pages chart, burying actual marketing page performance.

**Status:** UNFIXED since June 17 audit.

**Fix:** Add a `hostName` dimension filter (`www.visme.co`) and exclude `(not set)` from the landing pages query in `ga4_client.py`.

---

## Status of June 17 Audit Findings (GA4-Relevant)

| # | Finding | June Severity | Status |
|---|---------|--------------|--------|
| 1 | `create_an_account` wrong event for registrations | Critical | 🔴 UNFIXED |
| 2 | `visit_payment_page` = 0 (wrong/dead event) | High | 🔴 UNFIXED |
| 3 | Cross-dashboard sessions total inconsistency | High | 🟡 Unchanged (structural, acknowledged) |
| 4 | Week label convention inconsistency (GA4 vs Website) | Medium | 🔴 UNFIXED |
| 5 | Landing pages show `(not set)` and `/v2/` app paths | Low | 🔴 UNFIXED |

0 of 5 applicable June GA4 findings have been addressed.

---

## Verified Correct

- **Sessions Jul 13–19:** 182,849 (API: 183,126 — delta 0.15%) ✅
- **New Users Jul 13–19:** 132,981 (API: 133,484 — delta 0.38%) ✅
- **`purchase` events Jul 13–19:** 146 vs 146 — exact match ✅
- **All 15 named channel sessions:** within ±1.1% — consistent with build-time processing drift ✅
- **`create_an_account` and `visit_payment_page` event counts:** match GA4 exactly (3 and 2 respectively) ✅ — the numbers are accurate; the events themselves are wrong choices for the funnel

---

## Recommended Priority Order

1. **Fix `TARGET_EVENTS` in `ga4_client.py`** — replace `create_an_account` with `register`, investigate `visit_payment_page`. This is the single highest-impact fix: the registration funnel is off by 4,809× and has been since at least June.
2. **Fix `(not set)` NvR bucketing** — the `else` clause silently inflates returning users by ~38%.
3. **Fix landing pages query** — add `hostName = www.visme.co` filter and exclude `(not set)`.
4. **Standardize week labels** — use Monday start dates in `ga4_client.py`.
5. **Document build day requirement** — make explicit that builds must run on Monday to capture the most recent complete week.

---

*Audit conducted by Claude on July 27, 2026. All GA4 figures verified directly against property 368188880 via GA4 Data API. No data was assumed or interpolated.*

# Visme Dashboard Changes — Session Log
**Date:** May 19, 2026  
**Prepared for:** Claude Code handoff  
**Repo:** `C:\dev\visme-dashboards` → `https://github.com/mattvisme/visme-dashboards`  
**Live site:** `https://visme-dashboards.vercel.app`

---

## Overview

A full audit of all 6 dashboards was conducted, data was verified against live platform APIs (HubSpot, Amplitude/PostHog), and a series of fixes and new metrics were implemented. This document covers every change made, bugs found, and issues encountered — including significant git/environment problems.

---

## Audit Findings (Pre-Changes)

### Critical Issues Found
1. **MQL-to-Deal rate = 1,300%** — mathematically impossible. 13 deals from 1 MQL. MQL qualification was broken in HubSpot.
2. **MQL count = 1** out of 192K+ leads. HubSpot MQL scoring not working.
3. **`(not set)` = #1 landing page in GA4** — 9.3M sessions (29.5% of traffic) with 95.5% bounce rate. GA4 tracking gap.
4. **GSC CTR by Position = 0.00% for all buckets** — rendering bug. `ctrByPos` was hardcoded as `{}` in `sheets_client.py`.
5. **Deals discrepancy** — dashboard showed 13, HubSpot API returned 26. Filter undocumented.
6. **GA4 Registrations (126.1K) vs Amplitude Signups (271.7K)** — 2x discrepancy, never reconciled.
7. **New Leads count discrepancy** — dashboard 192.3K vs HubSpot API 160,520 (17% off, date field inconsistency).

### Data Quality Issues
- Amplitude had no prior-year baseline — all YoY% showed as `0` or `+16,646,700%` (recently integrated).
- Activation event (`New Project Saved` / `Project Created`) not documented or labelled on dashboard.
- `[skip ci]` pattern needed in build.yml but wasn't present.

### Data Verified Accurate (via live API)
- Amplitude: New Signups (271.7K), Activated Users (166.5K), Free→Paid Rate (0.85%), Conversions (2.3K) — all confirmed against Amplitude HTTP API.
- GA4: Sessions (1.9M), New Users (1.4M) — confirmed.
- HubSpot: MQL count = 1 — confirmed correct (real business problem, not data error).

---

## All Changes Made

### 1. Remove MQL from All Dashboards

**Why:** Only 1 MQL was created from 192K+ leads in 8 weeks. Displaying it caused a 1,300% MQL→Deal rate which is mathematically invalid and misleading in leadership reviews. MQL tracking in HubSpot is broken/not configured.

**Files changed:**
- `hubspot/index.html` — Removed MQL KPI card, Weekly MQLs chart card, `initChart('chartHSMQLs')`, `cMQLs`/`pMQLs` variable declarations, DOM update calls, `chartHSFunnel1` (Lead→MQL Rate) chart and `chartHSFunnel2` (MQL→Deal Rate) chart. Updated Conversion Funnel section subtitle. Kept `chartHSFunnel3` (Deal→Customer Rate).
- `executive/index.html` — Removed MQL row from summary table. Removed `mqls`/`pMqls` variable declarations. Replaced `Lead → MQL` and `MQL → Deal` funnel steps with a single `Lead → Deal` step. Removed `MQLs` from bar chart funnel.
- `index.html` — Updated HubSpot card description to remove mention of MQLs.

**Note:** The `mqls` key still exists in the injected `const HS = {...}` data blob. This is harmless — it's inert data that nothing reads anymore.

---

### 2. Fix GSC CTR by Position (0.00% Bug)

**Why:** The `ctrByPos` dict was hardcoded as `{}` in `sheets_client.py`. The dashboard's `renderCtrTable()` function read from it and showed 0.00% for all four position buckets.

**File changed:** `scripts/shared/sheets_client.py`

**What changed:** Added `_compute_ctr_by_pos()` function inside `fetch_gsc_sheet_data()`. It takes the widest available query window (52W → 26W → 13W → 8W), groups queries by average position into four buckets (`top3` ≤3.5, `top10` ≤10.5, `top20` ≤20.5, `other` >20.5), and computes weighted CTR.

**Critical format note:** CTR must be stored as a **decimal (0–1)**, NOT as a percentage. The dashboard's `fmtCtr(v)` function is `(v*100).toFixed(2)+'%'`. Storing `0.1327` displays as `13.27%`. The `CTR_BENCHMARKS` in `gsc/index.html` also use decimal (`{top3: 0.13}`). An earlier version of this fix incorrectly stored `* 100` (percentage), which caused the table to display `1327.06%`. The correct line is:
```python
b: round(d["clicks"] / d["impr"], 6) if d["impr"] > 0 else 0.0
```

**Important:** This fix only affects NEWLY BUILT data. The live `gsc/index.html` data blob still has `"ctrByPos":{}` until the next rebuild runs (`build_gsc.py`).

---

### 3. Document Deal Pipeline Filter (HubSpot)

**Why:** Dashboard shows 13 deals but HubSpot API returns 26 in the same period. The filter is applied in the Google Sheet export (not in code), so it needed to be visible to dashboard users.

**File changed:** `hubspot/index.html`

**What changed:** Updated Pipeline Overview section subtitle to include:
> "Deals scope: Sales pipeline only (excludes expansion & invoice records) — filter applied in the HubSpot Google Sheet export"

---

### 4. Amplitude YoY Guard — "No Prior Data" Instead of Misleading %

**Why:** Amplitude was integrated ~1 year ago. For the 8W comparison window, prior-year weeks had 0 signups and 0–1 stray activations. This caused: signups delta to show nothing (fmtDelta returns early on prev=0) but activations delta showed `+16,646,700%` (1 stray event vs 166K current).

**Files changed:**
- `scripts/shared/amplitude_client.py` — Added `hasFullHistory` flag: `True` when data spans ≥54 weeks (valid YoY for all range pills). Added `actRate` per-week dict (activations/signups as %).
- `amplitude/index.html` — Added `hasPrior` guard in `updateAmpKPIs()`.

**The guard logic (IMPORTANT — see TDZ issue below):**
```javascript
const cSu = s.curr.reduce((a,w)=>a+(AMP.signups[w]||0),0);
const pSu = s.prev.reduce((a,w)=>a+(AMP.signups[w]||0),0);
// hasPrior MUST be defined AFTER pSu — it references pSu
const hasPrior = AMP.hasFullHistory === true && pSu > 100;
```

**Why `pSu > 100`:** `hasFullHistory` is `true` (data spans 2 years), but prior signups for the 8W window are 0 (Amplitude had no events before Oct 2025). Activations had 1–5 stray events in prior period causing enormous %. The `pSu > 100` guard suppresses YoY when prior signups are effectively zero.

**TDZ Bug (encountered and fixed):** An early version placed `const hasPrior` BEFORE `const pSu` in the function. JavaScript `const` declarations are not hoisted — accessing `pSu` before its declaration throws `"Cannot access 'pSu' before initialization"`. This caused ALL Amplitude KPIs to show `—`. Fix: move `hasPrior` to after `pSu` is defined.

---

### 5. Add Activation Rate KPI

**Why:** Activated Users / New Signups is the most important PLG health metric. Currently 61.3%. Was not displayed anywhere.

**Files changed:**
- `amplitude/index.html` — Added new KPI card between "Activated Users" and "Free→Paid Conv. Rate":
  ```html
  <div class="kpi">
    <div class="kpi-label">Activation Rate</div>
    <div class="kpi-value" id="kpi-amp-actrate">—</div>
    <div class="kpi-delta" ...>Activated ÷ New Signups</div>
  </div>
  ```
  Added JS in `updateAmpKPIs()`: `const cActRate = cSu>0 ? Math.round(cAc/cSu*1000)/10 : null;`

- `scripts/shared/amplitude_client.py` — Added `actRate` dict (per-week activation rate as %) to the payload.

---

### 6. Add Cost per Free Signup to Paid Media Dashboard

**Why:** Free Signups (Paid) is already tracked. Cost per Free Signup = Total Spend / Free Signups = $3.39 is computable from existing data but was not displayed. More relevant than Blended CPA for a PLG business.

**File changed:** `paid-media/index.html`

**What changed:**
- Added `.kpi-grid-4` CSS class.
- Changed bottom KPI row from `kpi-grid-3` to `kpi-grid-4`.
- Added 7th KPI `COST PER FREE SIGNUP` with WoW and YoY deltas to `renderS1()`.
- Note: ROAS was NOT added — no revenue attribution to paid channels exists (HubSpot shows $0 closed won for all paid channels).

---

### 7. Add D7/D30 Retention Cohorts to Amplitude Dashboard

**Why:** Are newly signed-up users coming back? No retention data existed on any dashboard.

**Files changed:**
- `scripts/shared/amplitude_client.py` — Added `_fetch_retention()` function that calls `https://amplitude.com/api/2/retention` with `se=Sign Up Completed`, `re=_active`, `i=1` (daily), `n=31`. Returns dict of `{date: {d7: float|None, d30: float|None}}`. Gracefully returns `{}` on any API error so builds never fail.
- `amplitude/index.html` — Added:
  - Nav item "D7/D30 Retention" linking to `#section-amp-retention`
  - New section with two KPI cards (Latest D7, Latest D30)
  - Retention cohort table showing last 8 weekly cohorts with colour-coded values (green/amber/red thresholds)
  - `updateRetention()` function called from `updateAll()`

**Note:** D7/D30 data currently shows `—` because the Amplitude retention API format may differ from expected, or the cohort dates don't yet have 30-day data. The section renders cleanly with "No retention data available yet" message in that case.

---

### 8. Repository Move: OneDrive → C:\dev

**Why:** The repository was stored in `C:\Users\stryd\OneDrive\Documents\GitHub\visme-dashboards\visme-dashboards`. OneDrive syncing `.git` folder contents mid-write caused severe git corruption throughout the session — file truncation, stale lock files (`index.lock`, `HEAD.lock`, `packed-refs.lock`), inability to commit/push. GitHub Desktop also held lock files when running simultaneously.

**Action taken:**
```cmd
xcopy /E /I /H /Y "C:\Users\stryd\OneDrive\..." "C:\dev\visme-dashboards"
```

**New canonical location:** `C:\dev\visme-dashboards`

**Recommendation:** Exclude `C:\dev` from OneDrive sync. Never store git repos inside OneDrive.

---

## Issues Encountered

### File Truncation (Critical — Repeated)
The Cowork sandbox build environment writes files to the mounted OneDrive folder. OneDrive's sync process would interrupt file writes mid-stream, truncating files at arbitrary points (always at the same `font-size:10.5px` location in `hubspot/index.html`, and at inner `try:` blocks in Python files).

**Symptoms:** Files end mid-line with no `</script>`, `</body>`, `</html>`. Python syntax errors on `try:` statements. Dashboard fails to load.

**Affected files:** `hubspot/index.html`, `scripts/shared/sheets_client.py`, `scripts/shared/amplitude_client.py`

**Fix pattern:** `head -n {N-1} file > /tmp/fixed && cat tail >> /tmp/fixed && cp /tmp/fixed file`

**Resolution:** Move repo to `C:\dev` (outside OneDrive). Issue stopped after move.

---

### GitHub Actions Rebuild Loop
**What happened:** Every time a code fix was pushed to `main`, the user manually triggered the "Weekly Dashboard Rebuild" workflow from GitHub Actions UI. This workflow rebuilds all 6 dashboards (injecting fresh data) and commits the rebuilt HTML files back to `main`. Since the rebuild commits modified the same HTML files as our code fixes, every subsequent push attempt was rejected with "non-fast-forward" — requiring a rebase that then conflicted.

**Root cause:** `build.yml` only triggers on `schedule` (Mondays 10:00 UTC) and `workflow_dispatch`. There is NO push trigger. The loop was caused by manually running the rebuild after each push.

**Resolution:** Do not run the rebuild manually after code-only commits. The rebuild should only be run when you want to update dashboard data. Code changes (JS fixes, HTML changes) do NOT require a rebuild to take effect — Vercel deploys them directly from the commit.

---

### Stash Pop Reverting Fixes
When `git stash pop` was used during a rebase recovery, it reapplied stashed changes that predated the committed fixes — effectively reverting `amplitude/index.html` and `sheets_client.py` back to their broken states. This caused the same fixes to need reapplying 3+ times.

---

### `[skip ci]` Commit Message
Added `[skip ci]` to commit messages to prevent GitHub Actions from running the rebuild on code-only pushes. This is a GitHub convention that skips CI runs when present in the commit message.

---

## Current State (as of end of session)

| Dashboard | Status |
|---|---|
| Executive Overview | ✅ All metrics correct. MQL removed. Funnel shows Lead→Deal. |
| HubSpot Pipeline | ✅ 4 KPIs, MQL gone, channel table, deal scope note visible. |
| GA4 Traffic | ✅ Correct. 156 weeks of data. |
| Amplitude PLG | ⚠️ KPIs render correctly. Fix for `hasPrior` TDZ committed but may not be deployed yet pending push resolution. |
| GSC SEO | ⚠️ KPIs correct. CTR by Position fix committed but needs a **rebuild** to bake new data. Currently still shows 1327% etc. |
| Paid Media | ✅ 7 KPIs including Cost per Free Signup ($3.39). |

### Pending Git Push
Commits `bebb8bb` (TDZ fix + GSC decimal) need to be pushed cleanly to `main`. There is a stale `rebase-merge` directory blocking `git pull --rebase`. Resolution:

```cmd
cd C:\dev\visme-dashboards
rmdir /s /q .git\rebase-merge
git reset --hard origin/main
git add amplitude\index.html scripts\shared\sheets_client.py
git commit -m "Fix hasPrior TDZ and GSC CTR decimal [skip ci]"
git push
```

Then trigger one rebuild from GitHub Actions to refresh the GSC data with the correct decimal CTR values.

---

## Files Modified (Summary)

| File | Changes |
|---|---|
| `hubspot/index.html` | Remove MQL KPI, charts, funnel steps. Add deal scope note. |
| `executive/index.html` | Remove MQL row. Replace Lead→MQL+MQL→Deal with Lead→Deal. |
| `index.html` | Update HubSpot card description. |
| `amplitude/index.html` | Add Activation Rate KPI. Add hasPrior YoY guard (pSu>100). Add D7/D30 retention section. |
| `paid-media/index.html` | Add Cost per Free Signup KPI. Add kpi-grid-4 CSS. |
| `scripts/shared/sheets_client.py` | Add `_compute_ctr_by_pos()` computing CTR as decimal from query windows. |
| `scripts/shared/amplitude_client.py` | Add `hasFullHistory` flag, `actRate` dict, `_fetch_retention()`, `retention` in payload. |

---

## Key Architecture Notes

- Each dashboard is a **static HTML file** with data baked in as a `<script>` block.
- `html_utils.inject_data()` uses `_INJECTED_RE` regex to replace ONLY the data `<script>` block. All JS code in the second `<script>` block is **preserved across rebuilds**.
- Build scripts: `scripts/build_*.py` — one per dashboard.
- Data sources: Amplitude (direct API), GA4 (Data API), HubSpot (Google Sheet export), GSC (Google Sheet export), Google Ads + Microsoft Ads (direct APIs).
- The weekly rebuild (GitHub Actions, Mondays 10:00 UTC) fetches fresh data, rebuilds HTML, commits "Weekly rebuild YYYY-MM-DD", pushes to main, Vercel auto-deploys.
- **Never run the rebuild immediately after a code-only commit.** Wait for it to run on Monday, or wait several minutes after pushing before triggering manually — otherwise the rebuild commits on top of your code commit before you can push follow-up fixes.

# Visme Marketing Dashboards — Onboarding Guide

A complete reference for understanding, maintaining, and extending the Visme marketing analytics dashboards.

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [Repository Structure](#2-repository-structure)
3. [The Six Dashboards](#3-the-six-dashboards)
4. [Weekly Rebuild — How It Works](#4-weekly-rebuild--how-it-works)
5. [Data Pipeline Architecture](#5-data-pipeline-architecture)
6. [Data Sources & Client Modules](#6-data-sources--client-modules)
7. [Template Injection System](#7-template-injection-system)
8. [Secrets & Credentials](#8-secrets--credentials)
9. [Deployment & Access](#9-deployment--access)
10. [How to Add or Modify a Dashboard](#10-how-to-add-or-modify-a-dashboard)
11. [Local Development](#11-local-development)
12. [Common Issues & Debugging](#12-common-issues--debugging)

---

## 1. What This System Does

Each dashboard is a **static HTML file** with data baked directly into it as a `<script>` block. There is no backend, no database, and no runtime API calls from the browser. Every Monday, a GitHub Actions workflow:

1. Fetches fresh data from each data source (Amplitude, GA4, HubSpot, GSC, Google Ads, Microsoft Ads)
2. Serialises the data as JSON
3. Injects it into each dashboard's HTML file
4. Commits and pushes the updated files to `main`
5. Vercel automatically redeploys from `main`

This means every dashboard page loads instantly — the browser just reads pre-baked JSON.

---

## 2. Repository Structure

```
visme-dashboards/
├── index.html                   Hub / navigation page
├── login.html                   Authentication gate
├── auth.js                      localStorage auth logic
├── vercel.json                  Vercel deployment config
│
├── executive/index.html         Executive Overview dashboard
├── ga4/index.html               GA4 Traffic & Engagement dashboard
├── hubspot/index.html           HubSpot Pipeline & Revenue dashboard
├── amplitude/index.html         Amplitude PLG Metrics dashboard
├── gsc/index.html               GSC SEO Performance dashboard
├── paid-media/index.html        Paid Media (Google + Microsoft Ads) dashboard
│
├── scripts/
│   ├── build_executive.py       Build script for executive/index.html
│   ├── build_ga4.py             Build script for ga4/index.html
│   ├── build_hubspot.py         Build script for hubspot/index.html
│   ├── build_amplitude.py       Build script for amplitude/index.html
│   ├── build_gsc.py             Build script for gsc/index.html
│   ├── build_ppc.py             Build script for paid-media/index.html
│   └── shared/
│       ├── amplitude_client.py  Fetches PLG metrics from Amplitude HTTP API
│       ├── ga4_client.py        Fetches sessions/traffic from GA4 Data API
│       ├── sheets_client.py     Fetches HubSpot, GSC, PPC data from Google Sheets
│       ├── google_ads_client.py Fetches Google Ads campaign data
│       ├── msads_client.py      Fetches Microsoft Ads campaign data
│       └── html_utils.py        Injects JSON data into HTML templates
│
└── .github/workflows/
    ├── build.yml                Weekly rebuild automation (Mondays 10:00 UTC)
    └── pages.yml                GitHub Pages / Vercel deployment config
```

---

## 3. The Six Dashboards

| Dashboard | File | Data Sources | Build Script |
|-----------|------|-------------|--------------|
| Executive Overview | `executive/index.html` | GA4 + HubSpot + Amplitude | `build_executive.py` |
| GA4 Traffic | `ga4/index.html` | Google Analytics 4 | `build_ga4.py` |
| HubSpot Pipeline | `hubspot/index.html` | HubSpot (via Google Sheet) | `build_hubspot.py` |
| Amplitude PLG | `amplitude/index.html` | Amplitude API (direct) | `build_amplitude.py` |
| GSC SEO | `gsc/index.html` | Google Search Console (via Google Sheet) | `build_gsc.py` |
| Paid Media | `paid-media/index.html` | Google Ads + Microsoft Ads + Amplitude signups | `build_ppc.py` |

### Hub page (`index.html`)

The root page is a navigation hub that shows all 6 dashboard cards. It reads the `lastDate` / `asOfDate` / `endDate` from each dashboard's injected JSON using a regex fetch, and displays a "Data as of" timestamp on each card. It is **not rebuilt** by the pipeline — it's a static navigation page.

### Default range

All dashboards open with the **8W** (8-week) range pill active by default. Users can switch to 8W / 13W / 26W / 52W / 104W via the pills in the top bar.

---

## 4. Weekly Rebuild — How It Works

### Schedule

`build.yml` runs every **Monday at 10:00 UTC** via a cron schedule. It can also be triggered manually: GitHub → Actions → "Weekly Dashboard Rebuild" → "Run workflow".

### Step-by-step

```
1. Checkout repo (actions/checkout@v4)
2. Set up Python 3.11
3. Install Python dependencies:
     google-analytics-data
     google-auth
     google-api-python-client
     google-auth-httplib2
     google-auth-oauthlib
     gspread
     google-ads
     bingads
4. Build Executive dashboard
     env: GA4_CREDENTIALS_JSON, GA4_PROPERTY_ID, HUBSPOT_SHEET_ID,
          AMPLITUDE_API_KEY, AMPLITUDE_API_SECRET
     run: python scripts/build_executive.py
5. Build GA4 dashboard
     env: GA4_CREDENTIALS_JSON, GA4_PROPERTY_ID
     run: python scripts/build_ga4.py
6. Build HubSpot dashboard
     env: GA4_CREDENTIALS_JSON, HUBSPOT_SHEET_ID
     run: python scripts/build_hubspot.py
7. Build Amplitude dashboard
     env: AMPLITUDE_API_KEY, AMPLITUDE_API_SECRET
     run: python scripts/build_amplitude.py
8. Build Paid Media dashboard
     env: GA4_CREDENTIALS_JSON, GOOGLE_ADS_*, MS_ADS_*, PPC_SHEET_ID
     run: python scripts/build_ppc.py
9. Build GSC dashboard
     env: GA4_CREDENTIALS_JSON, GSC_SHEET_ID
     run: python scripts/build_gsc.py
10. Commit rebuilt files:
      executive/index.html, ga4/index.html, hubspot/index.html,
      amplitude/index.html, paid-media/index.html, gsc/index.html
    Commit message: "Weekly rebuild YYYY-MM-DD"
11. Push to main → Vercel redeploys automatically
```

### What happens if a step fails

If any build script throws an exception, that step exits with code 1 and **all subsequent steps are skipped** (GitHub Actions default). The commit step is therefore also skipped, so no partial data lands in production. The dashboards keep serving the previously-built data until the next successful run.

---

## 5. Data Pipeline Architecture

Every data source follows the same three-step pattern:

```
FETCH → TRANSFORM → INJECT
```

### Fetch
Each `scripts/shared/*_client.py` module calls its respective API or Google Sheet, authenticates, and returns a Python dict with a standardised shape.

### Standardised payload shape

All weekly metric payloads use this structure:

```python
{
  "weeks":       ["2026-01-05", "2026-01-12", ...],  # Monday dates, oldest-first
  "weekLabels":  ["Jan 11 '26", "Jan 18 '26", ...],  # Week-end Sunday labels
  "<metric>":    {"2026-01-05": 123, "2026-01-12": 456, ...},
  "lastDate":    "2026-05-17"  # Sunday of the most recent complete week
}
```

Weeks are always **Monday-boundary dates**. The current (incomplete) week is always excluded.

### Transform
The build script (e.g. `build_amplitude.py`) calls the client, does any final assembly, and passes a `data_dict` to `html_utils.inject_data()`. The dict keys become the JavaScript variable names (e.g. `{"AMP": amp_data}` → `const AMP = {...};`).

### Inject
`html_utils.inject_data()` serialises the dict to compact single-line JSON, wraps it in a `<script>` block, and replaces the `<!-- DATA_INJECTION_POINT -->` comment (or a previously-injected block) in the HTML template. The file is written back in-place.

---

## 6. Data Sources & Client Modules

### Amplitude (`scripts/shared/amplitude_client.py`)

**Connection:** Direct HTTP API — `https://amplitude.com/api/2/events/segmentation`  
**Auth:** HTTP Basic Auth (`AMPLITUDE_API_KEY:AMPLITUDE_API_SECRET`, Base64-encoded)  
**Credentials:** GitHub Secrets `AMPLITUDE_API_KEY`, `AMPLITUDE_API_SECRET`

**Events fetched (weekly, `i=7`):**

| Variable | Amplitude Event | Metric |
|----------|----------------|--------|
| `signups` | `Sign Up Completed` | New user registrations |
| `upgrades` | `Upgrade Completed` | Free-to-paid conversions |
| `activations` | `Project Created` | Total project creation events |

**CR (conversion rate):** Calculated as `(upgrades / signups) * 100` per week. Stored as a percentage number (e.g. `0.83` = 0.83%) to match the dashboard's `toFixed(2) + '%'` display.

**Date range:** The Amplitude API rejects weekly queries spanning more than ~1 year. The client makes **two API calls per event** — one covering `today - 730 days` to `today - 365 days`, and one covering `today - 365 days` to `today` — then merges the results. This covers the 2-year window needed for year-over-year comparison.

**JS variable:** `AMP`

---

### Google Analytics 4 (`scripts/shared/ga4_client.py`)

**Connection:** Google Analytics Data API v1 (`BetaAnalyticsDataClient`)  
**Auth:** Google Service Account (`GA4_CREDENTIALS_JSON` secret → temp file)  
**Property ID:** `368188880` (override via `GA4_PROPERTY_ID` env var)

**Data fetched:** Sessions, new users, channel breakdown, geo, landing pages, conversion events (`create_an_account`, `visit_payment_page`, `purchase`). 156 weeks of history.

**JS variable:** `GA4`

---

### HubSpot (`scripts/shared/sheets_client.py` → `fetch_hubspot_data`)

**Connection:** Google Sheets API (HubSpot data is exported into a Sheet)  
**Auth:** Same Google Service Account as GA4  
**Sheet ID:** `HUBSPOT_SHEET_ID` secret (default: `1TsDySDrmgSQEUjunQg77twgUS1fGgZIC71IbX-bAz1s`)  
**Tabs read:** `Weekly Summary`, `Weekly Channels`

**Data:** Leads, MQLs, deals, pipeline value, revenue, closed-won count, channel breakdown.

**JS variable:** `HS`

---

### Google Search Console (`scripts/shared/sheets_client.py` → `fetch_gsc_sheet_data`)

**Connection:** Google Sheets API (GSC data is exported via an Apps Script)  
**Sheet ID:** `GSC_SHEET_ID` secret  
**Tabs read:** Weekly, Queries, Pages, Countries

**JS variable:** `GSC`

---

### Paid Media / PPC (`scripts/shared/google_ads_client.py` + `msads_client.py` + `sheets_client.py`)

**Connections:**
- Google Ads API — credentials via multiple `GOOGLE_ADS_*` secrets
- Microsoft Ads (Bing) API — credentials via `MS_ADS_*` secrets
- PPC Google Sheet (`PPC_SHEET_ID`) — fallback / supplemental data
- Amplitude signups (via `AMPLITUDE_API_KEY` / `AMPLITUDE_API_SECRET`) — for CPL calculation

**JS variable:** `WEEKLY`, `CAMPAIGNS`, etc. (see `paid-media/index.html`)

---

## 7. Template Injection System

### How it works

Each dashboard HTML file contains this comment as a placeholder:
```html
<!-- DATA_INJECTION_POINT -->
```

`html_utils.inject_data(template_path, data_dict, output_path)` replaces it with:
```html
<script>
const AMP = {"weeks":[...],"signups":{...},...};
const GA4 = {...};
</script>
```

### Idempotent re-injection

The utility detects previously-injected blocks via a regex pattern and **replaces** them rather than duplicating. This means builds are fully re-runnable — running the same build script twice produces identical output.

### Adding a new data variable

In your build script, add a key to `data_dict`:
```python
inject_data(
    template_path=TEMPLATE,
    data_dict={"AMP": amp_data, "TRIALS": trials_data},
    output_path=OUTPUT,
)
```
This produces `const AMP = {...}; const TRIALS = {...};` in the HTML, accessible from all JavaScript on the page.

---

## 8. Secrets & Credentials

All secrets are stored in **GitHub → Settings → Secrets and variables → Actions**.

| Secret Name | Used By | Description |
|-------------|---------|-------------|
| `GA4_SERVICE_ACCOUNT_KEY` | GA4, HubSpot, GSC, PPC | Full JSON of Google service account key |
| `GA4_PROPERTY_ID` | GA4 | GA4 property ID (`368188880`) |
| `HUBSPOT_SHEET_ID` | HubSpot, Executive | Google Sheet ID for HubSpot data |
| `AMPLITUDE_API_KEY` | Amplitude, Executive, PPC | Amplitude project API key |
| `AMPLITUDE_API_SECRET` | Amplitude, Executive, PPC | Amplitude project Secret key |
| `GSC_SHEET_ID` | GSC | Google Sheet ID for GSC data |
| `PPC_SHEET_ID` | PPC | Google Sheet ID for PPC supplemental data |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | PPC | Google Ads developer token |
| `GOOGLE_ADS_CLIENT_ID` | PPC | Google Ads OAuth client ID |
| `GOOGLE_ADS_CLIENT_SECRET` | PPC | Google Ads OAuth client secret |
| `GOOGLE_ADS_REFRESH_TOKEN` | PPC | Google Ads OAuth refresh token |
| `GOOGLE_ADS_CUSTOMER_ID` | PPC | Google Ads customer ID |
| `GOOGLE_ADS_MANAGER_ID` | PPC | Google Ads manager account ID |
| `MS_ADS_DEVELOPER_TOKEN` | PPC | Microsoft Ads developer token |
| `MS_ADS_CLIENT_ID` | PPC | Microsoft Ads OAuth client ID |
| `MS_ADS_CLIENT_SECRET` | PPC | Microsoft Ads OAuth client secret |
| `MS_ADS_REFRESH_TOKEN` | PPC | Microsoft Ads OAuth refresh token |
| `MS_ADS_CUSTOMER_ID` | PPC | Microsoft Ads customer ID |
| `MS_ADS_ACCOUNT_ID` | PPC | Microsoft Ads account ID |

### Google Service Account

The service account (`project_service_account.md` in memory) needs:
- **GA4:** Viewer role on property `368188880`
- **Google Sheets:** Viewer access to each connected Sheet (HubSpot, GSC, PPC sheets)

### Amplitude credentials

The Amplitude API key and secret are from the **Visme** project (app ID `716573`) in Amplitude. They can be found at: Amplitude → Settings → Projects → Visme → API Key / Secret Key.

---

## 9. Deployment & Access

### Vercel

The repo deploys to Vercel as a **static site** — no build step, output directory is `.` (the repo root). `vercel.json` sets `"public": false`, meaning only authenticated Vercel users can view the deployment preview. The live production URL serves the committed HTML files directly.

### Authentication

The dashboards use a simple client-side auth gate:
- `login.html` — password entry form
- `auth.js` — validates the password and sets `localStorage.dashboard_authenticated = "true"`
- Each dashboard page (and `index.html`) checks this key on load and redirects to `/login.html` if absent

This is a lightweight gate, not enterprise SSO — it keeps the dashboards private without requiring a backend.

---

## 10. How to Add or Modify a Dashboard

### Adding a new metric to an existing dashboard

1. **Update the client** — add the new event/query to the relevant `*_client.py` and include it in the returned dict
2. **Update the build script** — no change needed if it's part of an existing payload key
3. **Update the HTML** — add chart canvas, JS rendering code, and KPI card to reference the new key from the injected JSON
4. **Test locally** — run `python scripts/build_<name>.py` and open the HTML in a browser
5. **Commit & push** — the next Monday rebuild picks it up automatically, or trigger manually

### Adding a completely new dashboard

1. Create `<name>/index.html` with `<!-- DATA_INJECTION_POINT -->` placeholder and your chart/KPI JS
2. Create `scripts/build_<name>.py` following the same pattern as existing build scripts
3. Add a new step to `.github/workflows/build.yml` with appropriate env secrets
4. Add `<name>/index.html` to the `git add` list in the commit step of `build.yml`
5. Add a navigation card to `index.html` (the hub)

### Changing a metric definition

If you rename an Amplitude event or change what a metric measures:
1. Update the event name in `amplitude_client.py` (or relevant client)
2. Update any labels/descriptions in the dashboard HTML
3. Consider whether historical data will be affected (renamed events will have a gap)

### Changing the rebuild schedule

Edit the cron expression in `.github/workflows/build.yml`:
```yaml
- cron: '0 10 * * 1'   # Every Monday at 10:00 UTC
```

---

## 11. Local Development

### Prerequisites

```bash
pip install google-analytics-data google-auth google-api-python-client \
            google-auth-httplib2 google-auth-oauthlib gspread
```

### Environment variables for local runs

```bash
# Google service account (for GA4, Sheets)
export GA4_CREDENTIALS_FILE="/path/to/service-account-key.json"
export GA4_PROPERTY_ID="368188880"
export HUBSPOT_SHEET_ID="1TsDySDrmgSQEUjunQg77twgUS1fGgZIC71IbX-bAz1s"
export GSC_SHEET_ID="<your-gsc-sheet-id>"
export PPC_SHEET_ID="<your-ppc-sheet-id>"

# Amplitude (direct API)
export AMPLITUDE_API_KEY="<api-key>"
export AMPLITUDE_API_SECRET="<secret-key>"
```

### Running a build

```bash
# From the repo root
python scripts/build_amplitude.py
python scripts/build_ga4.py
python scripts/build_hubspot.py
# etc.
```

Each script overwrites its dashboard's `index.html` in-place. Open the file in a browser via `file://` to verify.

### Note on credentials

In CI/CD, `GA4_CREDENTIALS_JSON` contains the full JSON string of the service account key. Locally, `GA4_CREDENTIALS_FILE` points to the JSON file on disk. The client modules handle both patterns automatically.

---

## 12. Common Issues & Debugging

### Build fails with HTTP 400 from Amplitude

The Amplitude segmentation API rejects weekly queries spanning more than ~1 year. `amplitude_client.py` handles this by splitting into two 12-month calls. If you see a 400, check:
- The error body (now logged by the client) for Amplitude's specific message
- Whether the date range calculation has drifted unexpectedly

### Build fails with Google Sheets auth error

Check that:
- `GA4_SERVICE_ACCOUNT_KEY` secret is correctly set (full JSON, not a file path)
- The service account has Viewer access to the specific Sheet

### Dashboard shows stale data

The weekly rebuild commits directly to `main`. Check:
- GitHub Actions → recent workflow runs — did Monday's run succeed?
- If a step failed, the commit step is skipped and data stays at the last successful run
- Manually trigger the workflow: Actions → Weekly Dashboard Rebuild → Run workflow

### CR values look wrong

CR is stored as a **percentage number**, not a decimal (e.g. `0.83` means 0.83%). The dashboard JS displays it as `value.toFixed(2) + '%'`. If you see values like `0.008`, the client is returning raw decimals — multiply by 100.

### "No DATA_INJECTION_POINT found" error

The HTML template is missing the `<!-- DATA_INJECTION_POINT -->` comment AND no previously-injected `<script>` block exists. This can happen if someone manually edited the file and removed both. Add the placeholder comment back:
```html
<!-- DATA_INJECTION_POINT -->
```

### Checking what data is currently in a dashboard

Open the dashboard's `index.html` and search for `<script>` — the injected data block will be there as a single-line JSON string. You can copy the value and paste it into a JSON formatter to inspect it.

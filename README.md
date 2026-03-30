# Visme Marketing Dashboards

Self-contained marketing analytics dashboards served via GitHub Pages. Each dashboard lives in its own folder and is rebuilt weekly by GitHub Actions.

**Hub URL:** https://mattvisme.github.io/visme-dashboards/

## Dashboard URLs

| Dashboard | URL | Data Sources |
|-----------|-----|--------------|
| Hub (all dashboards) | `/` | — |
| Executive Overview | `/executive/` | GA4 + HubSpot + Amplitude |
| GA4 Traffic & Engagement | `/ga4/` | GA4 |
| HubSpot Pipeline & Revenue | `/hubspot/` | HubSpot (Google Sheets) |
| Amplitude PLG Metrics | `/amplitude/` | Amplitude (Google Sheets) |
| GSC SEO Performance | `/gsc/` | Google Search Console API |
| Paid Media | `/paid-media/` | Google Ads (Google Sheets) + Amplitude |

## How It Works

Each dashboard HTML file has a `<!-- DATA_INJECTION_POINT -->` placeholder. The build scripts:
1. Fetch data from GA4 API or Google Sheets
2. Serialize it as JSON
3. Replace the placeholder with `<script>const GA4 = {...};</script>`
4. Commit the result back to `main`

GitHub Pages then serves the filled files statically — no server required.

## Triggering a Manual Rebuild

1. Go to the **Actions** tab in this repo
2. Click **Weekly Dashboard Rebuild**
3. Click **Run workflow** → **Run workflow**

The build takes ~2–3 minutes.

## Required GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Description |
|--------|-------------|
| `GA4_SERVICE_ACCOUNT_KEY` | Full JSON content of the service account key file |
| `GA4_PROPERTY_ID` | GA4 property ID: `368188880` |
| `HUBSPOT_SHEET_ID` | HubSpot Google Sheet ID: `1TsDySDrmgSQEUjunQg77twgUS1fGgZIC71IbX-bAz1s` |
| `AMPLITUDE_SHEET_ID` | Amplitude Google Sheet ID: `11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw` |
| `PPC_SHEET_ID` | PPC Google Sheet ID: `11YiWr1aHhwBto9JrgwnSGJLtyq1KEfJvs5ZRbkoWKho` |
| `GSC_SHEET_ID` | ID of the Google Sheet populated by the GSC Apps Script exporter |

The service account must have:
- **GA4 Data API** access (Viewer role on the GA4 property)
- **Google Sheets API** access (the service account email must have at least Viewer access on all spreadsheets)

## Adding a New Dashboard

1. Create a new folder (e.g., `linkedin/`)
2. Add a template `linkedin/index.html` with `<!-- DATA_INJECTION_POINT -->`
3. Add a build script `scripts/build_linkedin.py`
4. Add a step to `.github/workflows/build.yml`
5. Add a card to `index.html`
6. Add any required secrets to GitHub Settings

## Local Development

Run any build script locally with credentials:

```bash
# Set up credentials
export GA4_CREDENTIALS_FILE="/path/to/service-account.json"
export GA4_PROPERTY_ID="368188880"
export HUBSPOT_SHEET_ID="1TsDySDrmgSQEUjunQg77twgUS1fGgZIC71IbX-bAz1s"
export AMPLITUDE_SHEET_ID="11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw"
export GSC_SHEET_ID="your-gsc-sheet-id-here"

# Install dependencies
pip install google-analytics-data google-auth google-api-python-client gspread

# Build a dashboard
python scripts/build_ga4.py
python scripts/build_hubspot.py
python scripts/build_amplitude.py
python scripts/build_executive.py
python scripts/build_ppc.py
python scripts/build_gsc.py
```

Then open the output files in a browser (`file://` URL) to validate.

## Repository Structure

```
visme-dashboards/
├── index.html                  ← Hub / home page
├── executive/index.html        ← Executive overview
├── ga4/index.html              ← GA4 traffic & engagement
├── hubspot/index.html          ← HubSpot pipeline & revenue
├── amplitude/index.html        ← Amplitude PLG metrics
├── gsc/index.html              ← GSC SEO dashboard (template)
├── paid-media/index.html       ← Paid Media dashboard (template)
├── scripts/
│   ├── build_executive.py
│   ├── build_ga4.py
│   ├── build_hubspot.py
│   ├── build_amplitude.py
│   ├── build_ppc.py
│   ├── build_gsc.py
│   └── shared/
│       ├── ga4_client.py       ← GA4 Data API helper
│       ├── sheets_client.py    ← Google Sheets reader (HubSpot, Amplitude, PPC, GSC)
│       └── html_utils.py       ← Data injection helper
└── .github/workflows/
    ├── build.yml               ← Weekly rebuild (Mondays at 10am UTC)
    └── pages.yml               ← GitHub Pages deployment
```

## Related Repos

- **mattvisme/visme-dashboard** — Original combined dashboard (do not modify)
- **mattvisme/visme-dashboards** — This repo (multi-dashboard system)

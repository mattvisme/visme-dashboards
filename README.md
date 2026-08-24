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
| Marketing Channel Performance | `/channel-performance/` | GA4 (Traffic) + "Weekly Conversion & Signups channels" Google Sheet (Free/Paid, joined by a title classifier) |

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
| `CHANNEL_PERF_SHEET_ID` | "Weekly Conversion & Signups channels" Google Sheet ID (Week mode Free/Paid): `1F6h9jAVy7SEHiF1jS_HkFZ6Htu5fYJ-Q8yQxe0iJvCI` (optional — this default is baked into the code) |
| `CHANNEL_PERF_MONTHLY_SHEET_ID` | "Conversions / signups, monthly" Google Sheet ID (Month mode Free/Paid — true calendar-month source, not derived from the weekly sheet): `1JX0FMCDhhOlV4yEUW9vk9_BZqusKwNOGimcoYoJujzw` (optional — this default is baked into the code) |
| `AMPLITUDE_SHEET_ID` | Amplitude Google Sheet ID: `11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw` |
| `PPC_SHEET_ID` | PPC Google Sheet ID: `11YiWr1aHhwBto9JrgwnSGJLtyq1KEfJvs5ZRbkoWKho` |
| `GSC_SHEET_ID` | ID of the Google Sheet populated by the GSC Apps Script exporter |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL used by the anomaly-check workflows to post alerts |

The service account must have:
- **GA4 Data API** access (Viewer role on the GA4 property)
- **Google Sheets API** access (the service account email must have at least Viewer access on all spreadsheets)

> As of 2026-08-21: the "Weekly Conversion & Signups channels" sheet (`CHANNEL_PERF_SHEET_ID`) and the "Conversions / signups, monthly" sheet (`CHANNEL_PERF_MONTHLY_SHEET_ID`) have both been shared with the service account (Viewer). Each is fetched independently in `build_channel_performance.py` — losing access to one degrades only that mode's Free/Paid to "unavailable" without affecting the other, GA4 Traffic, or any other dashboard's weekly rebuild.

## Anomaly Detection & Slack Alerts

Two workflows run independently of the weekly rebuild (`build.yml`) and never modify or commit any `index.html` — they only read data and post to Slack.

| Workflow | Script | Schedule | Covers |
|----------|--------|----------|--------|
| `anomaly-check-daily.yml` | `scripts/check_traffic_anomaly.py` | Daily, 13:00 UTC | Website traffic bot-spike + PLG signup-drop |
| `anomaly-check-gsc.yml` | `scripts/check_gsc_anomaly.py` | Weekly, Wednesday 14:00 UTC | GSC clicks/position drop |

Both can also be run manually via **Actions → (workflow name) → Run workflow**.

Both checks pull "the last 48 hours," buffered `DATA_LAG_BUFFER_DAYS` (default 1) extra day behind today to avoid GA4 processing lag/timezone drift showing up as spurious 0s — by default that's the two days ending 2 days ago, not yesterday.

**Website traffic bot-spike check** — pulls the last 48 hours of sessions by channel and by source/medium, and flags:
- Any channel's daily sessions exceeding `CHANNEL_SPIKE_MULTIPLIER` (default 3x) its trailing 4-week same-day-of-week average
- `sessionSource=(not set)` AND `sessionMedium=(not set)` sessions exceeding `NOT_SET_SESSIONS_THRESHOLD` (default 200/day) combined with engagement rate below `NOT_SET_ENGAGEMENT_RATE_MAX` (default 5%) — the fingerprint from the Aug 4, 2026 bot-traffic incident

**PLG signup-drop check** — pulls the last 48 hours of `register` events by channel, and flags:
- Total daily signups dropping below `SIGNUP_TOTAL_DROP_RATIO` (default 50%) of the trailing 4-week average — likely a broken signup form or tracking break
- Any channel's signups dropping to zero for a full day when its 4-week average was meaningfully above zero (`SIGNUP_CHANNEL_ZERO_MIN_BASELINE`)
- Secondary/lower-severity signal: a channel's signups spiking `SIGNUP_SPIKE_MULTIPLIER` (default 3x)+ with no matching session spike, suggesting fake/bot signups rather than a tracking issue

**GSC drop check** — compares the most recently settled week (respecting `fetch_gsc_sheet_data`'s existing 3-day processing-lag exclusion) against the trailing 4-week average, and flags:
- Weekly clicks dropping more than `CLICKS_DROP_RATIO` (default 30%) vs. the trailing 4-week average
- Weekly average position worsening by more than `POSITION_WORSEN_DELTA` (default 3 positions) vs. the trailing 4-week average

**Tuning thresholds:** every threshold above is a named constant at the top of its script (`scripts/check_traffic_anomaly.py` or `scripts/check_gsc_anomaly.py`) — edit the constant and redeploy, no other logic changes needed.

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
python scripts/build_channel_performance.py
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
├── channel-performance/index.html ← Channel Performance (Traffic live from GA4; Free/Paid pending)
├── scripts/
│   ├── build_executive.py
│   ├── build_ga4.py
│   ├── build_hubspot.py
│   ├── build_amplitude.py
│   ├── build_ppc.py
│   ├── build_gsc.py
│   ├── build_channel_performance.py
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

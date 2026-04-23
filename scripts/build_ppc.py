#!/usr/bin/env python3
"""
scripts/build_ppc.py
Builds paid-media/index.html from Google Ads API + Microsoft Advertising API.

Usage (local dev):
    set GA4_CREDENTIALS_FILE=C:/Users/stryd/OneDrive/Documents/visme-marketing-491309-8316da126688.json
    set GOOGLE_ADS_DEVELOPER_TOKEN=...
    set MS_ADS_DEVELOPER_TOKEN=...
    set MS_ADS_CLIENT_ID=...
    set MS_ADS_CLIENT_SECRET=...
    set MS_ADS_REFRESH_TOKEN=...
    python scripts/build_ppc.py
"""

import os
import sys
import tempfile
from datetime import date, timedelta

# Force UTF-8 stdout on Windows so emoji in print() don't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.google_ads_client import fetch_all_google
from scripts.shared.msads_client import fetch_all_msads
from scripts.shared.sheets_client import fetch_amplitude_data, fetch_bing_weekly, fetch_ppc_data, fetch_google_ads_from_sheet
from scripts.shared.ga4_client import fetch_paid_search_new_users
from scripts.shared.html_utils import inject_data

# ─── PATHS ────────────────────────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "paid-media", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "paid-media", "index.html")

# ─── MONTHLY BUDGET CONFIG ────────────────────────────────────────────────────
# Update manually at the start of each month.

MONTHLY_BUDGETS = {
    "2026-01": 10000,
    "2026-02": 10000,
    "2026-03": 11111,
    "2026-04": 11111,
    "2026-05": 11111,
    "2026-06": 11111,
    "2026-07": 11111,
    "2026-08": 11111,
    "2026-09": 11111,
    "2026-10": 11111,
    "2026-11": 11111,
    "2026-12": 11111,
}

# ─── ENV VARS ─────────────────────────────────────────────────────────────────

GOOGLE_ADS_DEVELOPER_TOKEN = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "")
GOOGLE_ADS_MANAGER_ID      = os.environ.get("GOOGLE_ADS_MANAGER_ID",      "4091490058")
GOOGLE_ADS_CUSTOMER_ID     = os.environ.get("GOOGLE_ADS_CUSTOMER_ID",     "2405880186")
GOOGLE_ADS_CLIENT_ID       = os.environ.get("GOOGLE_ADS_CLIENT_ID",       "")
GOOGLE_ADS_CLIENT_SECRET   = os.environ.get("GOOGLE_ADS_CLIENT_SECRET",   "")
GOOGLE_ADS_REFRESH_TOKEN   = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN",   "")

MS_ADS_DEVELOPER_TOKEN = os.environ.get("MS_ADS_DEVELOPER_TOKEN", "")
MS_ADS_CLIENT_ID       = os.environ.get("MS_ADS_CLIENT_ID",       "")
MS_ADS_CLIENT_SECRET   = os.environ.get("MS_ADS_CLIENT_SECRET",   "")
MS_ADS_REFRESH_TOKEN   = os.environ.get("MS_ADS_REFRESH_TOKEN",   "")
MS_ADS_CUSTOMER_ID     = os.environ.get("MS_ADS_CUSTOMER_ID",     "169512962")
MS_ADS_ACCOUNT_ID      = os.environ.get("MS_ADS_ACCOUNT_ID",      "176012710")

AMPLITUDE_SHEET_ID = os.environ.get(
    "AMPLITUDE_SHEET_ID",
    "11E6j63Jq56o-G_EqwQ0ZCSH5ssTMLAAII4bbeK8p6zw",
)
PPC_SHEET_ID = os.environ.get(
    "PPC_SHEET_ID",
    "11YiWr1aHhwBto9JrgwnSGJLtyq1KEfJvs5ZRbkoWKho",
)


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _resolve_credentials_file():
    """Return path to a service-account JSON file (writes tempfile if needed)."""
    creds_json = os.environ.get("GA4_CREDENTIALS_JSON")
    if creds_json:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(creds_json)
        tmp.close()
        return tmp.name
    return os.environ.get(
        "GA4_CREDENTIALS_FILE",
        os.path.join(os.path.expanduser("~"), "Downloads",
                     "visme-marketing-491309-8316da126688.json"),
    )

def _empty_google():
    return {"weekly": [], "camps": [], "ads": [], "kw": [], "kw_weekly": [], "geo": {}}

def _empty_msads():
    return {"weekly": [], "camps": [], "ads": [], "kw": [], "kw_weekly": [], "geo": {}}


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Building paid-media/index.html")
    print("=" * 60)

    credentials_file = _resolve_credentials_file()

    # ── 1. Google Ads ─────────────────────────────────────────────────────────
    try:
        google_data = fetch_all_google(
            developer_token=GOOGLE_ADS_DEVELOPER_TOKEN,
            credentials_file=credentials_file,
            manager_id=GOOGLE_ADS_MANAGER_ID,
            customer_id=GOOGLE_ADS_CUSTOMER_ID,
            client_id=GOOGLE_ADS_CLIENT_ID,
            client_secret=GOOGLE_ADS_CLIENT_SECRET,
            refresh_token=GOOGLE_ADS_REFRESH_TOKEN,
        )
    except Exception as e:
        import traceback
        print(f"  ❌ Google Ads API FAILED: {type(e).__name__}: {e}")
        print("  Full traceback:"); traceback.print_exc()
        google_data = _empty_google()

    if not google_data["weekly"]:
        print("  ↳ No Google Ads API data — falling back to Google Sheet...")
        try:
            google_data = fetch_google_ads_from_sheet(PPC_SHEET_ID)
            print(f"    → {len(google_data['weekly'])} weeks, {len(google_data['camps'])} campaign rows from sheet")
        except Exception as e2:
            import traceback
            print(f"  ❌ Sheet fallback FAILED: {type(e2).__name__}: {e2}")
            print("  Full traceback:"); traceback.print_exc()

    # ── 2. Microsoft Ads ──────────────────────────────────────────────────────
    try:
        msads_data = fetch_all_msads(
            developer_token=MS_ADS_DEVELOPER_TOKEN,
            client_id=MS_ADS_CLIENT_ID,
            client_secret=MS_ADS_CLIENT_SECRET,
            refresh_token=MS_ADS_REFRESH_TOKEN,
            customer_id=MS_ADS_CUSTOMER_ID,
            account_id=MS_ADS_ACCOUNT_ID,
        )
    except Exception as e:
        import traceback
        print(f"  ❌ Microsoft Ads API FAILED: {type(e).__name__}: {e}")
        print("  Full traceback:"); traceback.print_exc()
        msads_data = _empty_msads()

    if not msads_data["weekly"]:
        print("  ↳ No MS Ads API data — falling back to Google Sheet (Bing Ads tab)...")
        try:
            sheet_weekly = fetch_bing_weekly(PPC_SHEET_ID)
            msads_data["weekly"] = sheet_weekly
            print(f"    → {len(sheet_weekly)} weeks from sheet")
        except Exception as e2:
            import traceback
            print(f"  ❌ Sheet fallback FAILED: {type(e2).__name__}: {e2}")
            print("  Full traceback:"); traceback.print_exc()

    # ── 3. GA4 paid-search new users ─────────────────────────────────────────
    print("⏳  GA4: paid search new users...")
    try:
        amp_by_week = fetch_paid_search_new_users(
            property_id=os.environ.get("GA4_PROPERTY_ID", "368188880"),
            credentials_file=credentials_file,
        )
        print(f"    → {len(amp_by_week)} weeks")
    except Exception as e:
        import traceback
        print(f"    ❌ GA4 paid search FAILED: {type(e).__name__}: {e}")
        print("    Full traceback:"); traceback.print_exc()
        amp_by_week = {}

    # ── 4. Merge WEEKLY ───────────────────────────────────────────────────────
    ms_by_week = {r["week_start"]: r for r in msads_data["weekly"]}

    merged_weekly = []
    for gw in google_data["weekly"]:
        ws = gw["week_start"]
        mw = ms_by_week.get(ws, {})
        merged_weekly.append({
            "week_start":    gw["week_start"],
            "week_end":      gw["week_end"],
            "label":         gw["label"],
            "g_spend":       gw["g_spend"],
            "g_clicks":      gw["g_clicks"],
            "g_impressions": gw["g_impressions"],
            "g_conversions": gw["g_conversions"],
            "m_spend":       mw.get("m_spend",       0.0),
            "m_clicks":      mw.get("m_clicks",       0),
            "m_impressions": mw.get("m_impressions",  0),
            "m_conversions": mw.get("m_conversions",  0.0),
            "ga4_new_users": amp_by_week.get(ws, 0),
        })

    # ── 5. Merge GEO ──────────────────────────────────────────────────────────
    all_states  = set(google_data["geo"]) | set(msads_data["geo"])
    merged_geo  = {}
    empty_g = {"g_spend": 0.0, "g_clicks": 0, "g_conversions": 0.0,
               "g_cpa": 0.0, "g_conv_rate": 0.0}
    empty_m = {"ms_spend": 0.0, "ms_clicks": 0, "ms_conversions": 0.0,
               "ms_cpa": 0.0, "ms_conv_rate": 0.0}
    for state in sorted(all_states):
        merged_geo[state] = {
            **google_data["geo"].get(state, empty_g),
            **msads_data["geo"].get(state, empty_m),
        }

    # ── 6. Build BUDGETS ──────────────────────────────────────────────────────
    spend_by_month = {}
    for row in merged_weekly:
        month = row["week_start"][:7]   # "YYYY-MM"
        spend_by_month[month] = spend_by_month.get(month, 0.0) + \
            row["g_spend"] + row["m_spend"]

    budgets_dict = {
        month: {
            "budget": budget,
            "spend":  round(spend_by_month.get(month, 0.0), 2),
        }
        for month, budget in MONTHLY_BUDGETS.items()
    }

    # ── 7. Inject ─────────────────────────────────────────────────────────────
    print("\n=== DATA SUMMARY ===")
    print(f"WEEKLY:   {len(merged_weekly)} weeks")
    print(f"CAMPS_G:  {len(google_data['camps'])} rows")
    print(f"CAMPS_M:  {len(msads_data['camps'])} rows")
    print(f"ADS_G:    {len(google_data['ads'])} rows")
    print(f"ADS_M:    {len(msads_data['ads'])} rows")
    print(f"KW_G:     {len(google_data['kw'])} rows")
    print(f"KW_M:     {len(msads_data['kw'])} rows")
    print(f"GEO:      {len(merged_geo)} states")
    print(f"BUDGETS:  {len(budgets_dict)} months")
    print("====================\n")

    inject_data(
        template_path=TEMPLATE,
        data_dict={
            "WEEKLY":     merged_weekly,
            "CAMPS_G":    google_data["camps"],
            "CAMPS_M":    msads_data["camps"],
            "ADS_G":      google_data["ads"],
            "ADS_M":      msads_data["ads"],
            "KW_G":       google_data["kw"],
            "KW_M":       msads_data["kw"],
            "KW_G_W":     google_data["kw_weekly"],
            "KW_M_W":     msads_data["kw_weekly"],
            "GEO":        merged_geo,
            "BUDGETS":    budgets_dict,
            "MS_ENABLED": True,
            "BUILD_DATE": date.today().strftime("%Y-%m-%d"),
            "generatedAt": merged_weekly[-1]["week_end"] if merged_weekly else "",
        },
        output_path=OUTPUT,
    )
    print("\nDone → paid-media/index.html")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Quick token test — authenticates and pulls the most recent week of MS Ads data."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from bingads import AuthorizationData, OAuthDesktopMobileAuthCodeGrant

developer_token = os.environ["MS_ADS_DEVELOPER_TOKEN"]
client_id       = os.environ["MS_ADS_CLIENT_ID"]
refresh_token   = os.environ["MS_ADS_REFRESH_TOKEN"]
customer_id     = os.environ.get("MS_ADS_CUSTOMER_ID", "169512962")
account_id      = os.environ.get("MS_ADS_ACCOUNT_ID",  "176012710")

print("Authenticating...")
auth = OAuthDesktopMobileAuthCodeGrant(client_id=client_id)
auth.request_oauth_tokens_by_refresh_token(refresh_token)
print(f"✅  Token refresh succeeded. Access token starts with: {auth.oauth_tokens.access_token[:20]}...")

auth_data = AuthorizationData(
    account_id=int(account_id),
    customer_id=int(customer_id),
    developer_token=developer_token,
    authentication=auth,
)

from scripts.shared.msads_client import fetch_weekly_msads
print("Fetching weekly MS Ads data...")
rows = fetch_weekly_msads(auth_data)
if rows:
    print(f"✅  Got {len(rows)} weeks. Most recent 2:")
    for r in rows[-2:]:
        print(f"    {r}")
else:
    print("⚠️  No rows returned.")

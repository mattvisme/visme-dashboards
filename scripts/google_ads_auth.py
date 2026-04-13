#!/usr/bin/env python3
"""
scripts/google_ads_auth.py
First-time OAuth setup for Google Ads API.

Run this ONCE locally to obtain a refresh token, then save it as the
GOOGLE_ADS_REFRESH_TOKEN GitHub secret.

Usage (with a client_secrets JSON file downloaded from Google Cloud Console):
    python scripts/google_ads_auth.py path/to/client_secrets.json

Usage (with env vars):
    set GOOGLE_ADS_CLIENT_ID=<your-client-id>
    set GOOGLE_ADS_CLIENT_SECRET=<your-client-secret>
    python scripts/google_ads_auth.py

A browser window will open. Sign in with the Google account that has access
to the Google Ads manager account and approve the permissions.
"""

import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    sys.exit("google-auth-oauthlib not installed. Run: pip install google-auth-oauthlib")

SCOPES = ["https://www.googleapis.com/auth/adwords"]


def main():
    # Accept client_secrets JSON file as optional positional arg
    if len(sys.argv) > 1:
        secrets_file = sys.argv[1]
        if not os.path.exists(secrets_file):
            sys.exit(f"Error: file not found: {secrets_file}")
        flow = InstalledAppFlow.from_client_secrets_file(secrets_file, scopes=SCOPES)
    else:
        client_id     = os.environ.get("GOOGLE_ADS_CLIENT_ID", "").strip()
        client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            sys.exit(
                "Usage: python scripts/google_ads_auth.py path/to/client_secrets.json\n"
                "   or: set GOOGLE_ADS_CLIENT_ID and GOOGLE_ADS_CLIENT_SECRET env vars"
            )
        client_config = {
            "installed": {
                "client_id":     client_id,
                "client_secret": client_secret,
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

    print("\nStarting OAuth flow...")
    print("A browser window will open. Sign in with the Google account")
    print("that has access to the Google Ads manager account.\n")

    try:
        credentials = flow.run_local_server(port=0, open_browser=True)
    except Exception as e:
        sys.exit(f"OAuth flow failed: {e}")

    print("\n" + "=" * 60)
    print("SUCCESS — tokens obtained.")
    print("=" * 60)
    print()
    print("REFRESH TOKEN (save as GOOGLE_ADS_REFRESH_TOKEN secret):")
    print(credentials.refresh_token)
    print()
    print("=" * 60)
    print("Next steps:")
    print("  1. Copy the refresh token above.")
    print("  2. Add to your .env file:")
    print("       GOOGLE_ADS_REFRESH_TOKEN=<paste here>")
    print("  3. Add to GitHub Secrets → Actions:")
    print("       GOOGLE_ADS_CLIENT_ID")
    print("       GOOGLE_ADS_CLIENT_SECRET")
    print("       GOOGLE_ADS_REFRESH_TOKEN")
    print("=" * 60)


if __name__ == "__main__":
    main()

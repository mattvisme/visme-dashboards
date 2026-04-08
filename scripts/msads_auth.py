#!/usr/bin/env python3
"""
scripts/msads_auth.py
First-time OAuth setup for Microsoft Advertising.

Run this ONCE locally to obtain a refresh token, then save it as the
MS_ADS_REFRESH_TOKEN GitHub secret. The token is long-lived and only
needs to be refreshed if it expires or is revoked.

Usage:
    set MS_ADS_CLIENT_ID=<your-azure-app-client-id>
    set MS_ADS_CLIENT_SECRET=<your-azure-app-client-secret>
    python scripts/msads_auth.py

The script opens your browser for Microsoft login. After you sign in,
Microsoft redirects to a blank page. Copy the full URL from the
address bar, paste it here, and the refresh token will be printed.
"""

import os
import sys
import webbrowser

try:
    from bingads import OAuthWebAuthCodeGrant
except ImportError:
    sys.exit("bingads SDK not installed. Run: pip install bingads")


REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeClient"


def main():
    client_id     = os.environ.get("MS_ADS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("MS_ADS_CLIENT_SECRET", "").strip()

    if not client_id:
        sys.exit("Error: MS_ADS_CLIENT_ID environment variable is not set.")
    if not client_secret:
        sys.exit("Error: MS_ADS_CLIENT_SECRET environment variable is not set.")

    authentication = OAuthWebAuthCodeGrant(
        client_id=client_id,
        client_secret=client_secret,
        redirection_uri=REDIRECT_URI,
    )

    auth_url = authentication.get_authorization_endpoint()
    print("\nOpening browser for Microsoft Advertising login...")
    print(f"\nIf the browser does not open automatically, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("After signing in, Microsoft will redirect to a blank page.")
    print("Copy the FULL URL from the browser address bar and paste it below.")
    print()
    redirect_url = input("Redirect URL: ").strip()

    if not redirect_url:
        sys.exit("No URL entered. Aborting.")

    try:
        authentication.request_oauth_tokens_by_response_uri(redirect_url)
    except Exception as e:
        sys.exit(f"Error exchanging code for tokens: {e}")

    refresh_token = authentication.oauth_tokens.refresh_token
    access_token  = authentication.oauth_tokens.access_token

    print("\n" + "=" * 60)
    print("SUCCESS — tokens obtained.")
    print("=" * 60)
    print()
    print("REFRESH TOKEN (save as MS_ADS_REFRESH_TOKEN secret):")
    print(refresh_token)
    print()
    print("ACCESS TOKEN (short-lived, for testing only):")
    print(access_token)
    print()
    print("=" * 60)
    print("Next steps:")
    print("  1. Copy the refresh token above.")
    print("  2. Go to GitHub → Settings → Secrets → Actions.")
    print("  3. Create or update secret: MS_ADS_REFRESH_TOKEN")
    print("  4. Paste the token as the secret value.")
    print("=" * 60)


if __name__ == "__main__":
    main()

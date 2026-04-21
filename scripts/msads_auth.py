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
    from bingads import OAuthDesktopMobileAuthCodeGrant
except ImportError:
    sys.exit("bingads SDK not installed. Run: pip install bingads")


REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeClient"


def main():
    client_id     = os.environ.get("MS_ADS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("MS_ADS_CLIENT_SECRET", "").strip()

    if not client_id:
        sys.exit("Error: MS_ADS_CLIENT_ID environment variable is not set.")

    authentication = OAuthDesktopMobileAuthCodeGrant(client_id=client_id)

    # matt@visme.com is a personal Microsoft account (live.com) — use consumers tenant
    import urllib.parse
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "scope": "https://ads.microsoft.com/msads.manage offline_access",
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "prompt": "login",
        "login_hint": "matt@visme.com",
    })
    auth_url = f"https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?{params}"
    print(f"\nOpen this URL in a private/incognito window (signs in as personal Microsoft account):\n\n{auth_url}\n")

    print("After signing in, Microsoft will redirect to a blank page.")
    print("Copy the FULL URL from the browser address bar and paste it below.")
    print()
    redirect_url = input("Redirect URL: ").strip()

    if not redirect_url:
        sys.exit("No URL entered. Aborting.")

    # Extract code from redirect URL manually
    import urllib.parse, requests as req
    parsed = urllib.parse.urlparse(redirect_url)
    qs = urllib.parse.parse_qs(parsed.query or parsed.fragment)
    code = (qs.get("code") or [""])[0]
    if not code:
        sys.exit(f"Could not find 'code' in redirect URL. Got: {redirect_url}")

    # Exchange code for tokens using the same tenant + redirect_uri
    resp = req.post(
        "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
        data={
            "client_id":    client_id,
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": REDIRECT_URI,
            "scope":        "https://ads.microsoft.com/msads.manage offline_access",
        },
        timeout=15,
    )
    tokens = resp.json()
    if "error" in tokens:
        sys.exit(f"Token exchange failed: {tokens.get('error')}: {tokens.get('error_description')}")

    refresh_token = tokens.get("refresh_token", "")
    access_token  = tokens.get("access_token", "")

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

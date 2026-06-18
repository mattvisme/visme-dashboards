#!/usr/bin/env python3
"""
scripts/build_auth.py
Injects the dashboard password into login.html at build time.

Reads dashboard_pw from the environment (loaded from .env.local if present).
Replaces the __DASHBOARD_PASSWORD__ placeholder in login.html with the actual value.

Environment variables:
    dashboard_pw    The password to protect the dashboards
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.local"))
except ImportError:
    pass

REPO_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGIN_HTML  = os.path.join(REPO_ROOT, "login.html")
PLACEHOLDER = "__DASHBOARD_PASSWORD__"


def main():
    password = os.environ.get("dashboard_pw")
    if not password:
        print("ERROR: dashboard_pw environment variable is not set.", file=sys.stderr)
        print("  - Locally: create .env.local with dashboard_pw=your-password", file=sys.stderr)
        print("  - CI/CD:   add dashboard_pw as a GitHub Actions secret", file=sys.stderr)
        sys.exit(1)

    with open(LOGIN_HTML, encoding="utf-8") as f:
        html = f.read()

    if PLACEHOLDER not in html:
        print(f"ERROR: placeholder '{PLACEHOLDER}' not found in login.html.", file=sys.stderr)
        print("  login.html may have already been built or the placeholder was removed.", file=sys.stderr)
        sys.exit(1)

    html = html.replace(PLACEHOLDER, password, 1)

    with open(LOGIN_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅  login.html updated — password injected")


if __name__ == "__main__":
    main()

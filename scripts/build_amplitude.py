#!/usr/bin/env python3
"""
scripts/build_amplitude.py
Fetches Amplitude PLG metrics directly from the Amplitude API and injects
them into amplitude/index.html.

Usage:
    python scripts/build_amplitude.py

Environment variables:
    AMPLITUDE_API_KEY     Amplitude project API key
    AMPLITUDE_API_SECRET  Amplitude project Secret key
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shared.amplitude_client import fetch_amplitude_data
from scripts.shared.html_utils import inject_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE  = os.path.join(REPO_ROOT, "amplitude", "index.html")
OUTPUT    = os.path.join(REPO_ROOT, "amplitude", "index.html")


def main():
    print("=" * 60)
    print("Building amplitude/index.html")
    print("=" * 60)

    amp_data = fetch_amplitude_data()

    inject_data(
        template_path=TEMPLATE,
        data_dict={"AMP": amp_data},
        output_path=OUTPUT,
    )
    print("Done.")


if __name__ == "__main__":
    main()

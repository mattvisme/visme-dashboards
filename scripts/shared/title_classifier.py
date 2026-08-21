"""
scripts/shared/title_classifier.py

Classifies a raw conversion-sheet `Title` value (e.g. "google.com", "GoogleCPC",
"Direct", "anonymous") into one of GA4's own channel groups, so the "Weekly
Conversion & Signups channels" Google Sheet can be joined against live GA4
Traffic data by channel.

IMPORTANT — scope of this classifier:
This implements ONLY the rules that were explicitly documented in the
colleague's handoff for the original artifact (see chat history, Section 2,
point 4: "Conversion-title classification"). It is deliberately NOT extended
with additional guessed domain categories (e.g. yahoo.com, search.brave.com,
perplexity.ai are all real Titles seen in the live sheet but were never on
the documented list, so they fall through to the generic Referral/Other
rules below, not to Organic Search or AI Assistant, even though a human
might reasonably put them there). Extending the exact-match alias table
below is the fix — see UNCLASSIFIED handling in sheets_client.py, which
surfaces every Title that fell through to "Referral" or "Other (Unclassified)"
so a human can review and extend this file with confidence, rather than
someone guessing more categories.

Returns a channel name matching GA4's own `sessionDefaultChannelGroup`
values, EXCEPT for "Other (Unclassified)", which is not a real GA4 channel —
it's a catch-all row for conversion titles this classifier can't place
anywhere, rendered as a distinct extra row in the dashboard, never merged
into a real GA4 channel.
"""

import re

OTHER_UNCLASSIFIED = "Other (Unclassified)"

# Exact-match alias table — documented 1:1 in the handoff.
EXACT_MAP = {
    "direct": "Direct",
    "n/a": "Unassigned",
    "googlecpc": "Paid Search",
    "bingcpc": "Paid Search",
    "android-app": "Direct",
    "ios-app": "Direct",
}

# Domain-list classification — documented examples only, from the handoff:
#   AI Assistant:     chatgpt.com, gemini.google.com
#   Organic Search:   google.com, bing.com, yandex.* , duckduckgo.com
#   Organic Social:   facebook.com, pinterest.com, reddit.com
#   Organic Video:    youtube.com
DOMAIN_CHANNELS = {
    "AI Assistant":    ["chatgpt.com", "gemini.google.com"],
    "Organic Search":  ["google.com", "bing.com", "duckduckgo.com"],
    "Organic Social":  ["facebook.com", "pinterest.com", "reddit.com"],
    "Organic Video":   ["youtube.com"],
}
# yandex.* — documented as a wildcard family (yandex.ru, yandex.com.tr,
# yandex.kz, yandex.by, yandex.uz all appeared in the actual GA4 export
# per the handoff's own sample rows), matched by prefix below rather than
# an exhaustive TLD list.
YANDEX_PREFIX = "yandex."

_DOMAIN_LOOKUP = {}
for _channel, _domains in DOMAIN_CHANNELS.items():
    for _d in _domains:
        _DOMAIN_LOOKUP[_d] = _channel

# "Looks like a domain" fallback — generic hostname shape, documented as
# defaulting to Referral in the handoff.
_DOMAIN_SHAPE_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*\.)+[a-z]{2,}$")


def classify_title(title: str) -> str:
    """
    Classify one raw conversion-sheet Title into a channel name.
    Case-insensitive on the exact-map and domain checks; the domain-shape
    fallback also lowercases first.
    """
    if title is None:
        return OTHER_UNCLASSIFIED
    raw = title.strip()
    if raw == "":
        return OTHER_UNCLASSIFIED

    key = raw.lower()

    if key in EXACT_MAP:
        return EXACT_MAP[key]

    # Strip a leading "www." before checking domain lists / shape, since
    # "www.google.com" and "google.com" should classify identically.
    host = key[4:] if key.startswith("www.") else key

    if host in _DOMAIN_LOOKUP:
        return _DOMAIN_LOOKUP[host]
    # subdomain match, e.g. "search.yahoo.com" would NOT match "yahoo.com"
    # here because yahoo.com is not documented — only exact / yandex-prefix
    # matches are honored, per the "don't invent categories" note above.
    for domain, channel in _DOMAIN_LOOKUP.items():
        if host.endswith("." + domain):
            return channel

    if host.startswith(YANDEX_PREFIX):
        return "Organic Search"

    if _DOMAIN_SHAPE_RE.match(host):
        return "Referral"

    return OTHER_UNCLASSIFIED

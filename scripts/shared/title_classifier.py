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


def match_source_medium(source_medium: str, known_titles_lower: dict):
    """
    Best-effort 1:1 match from a single GA4 `source_medium` string (e.g.
    "google / cpc") to a specific Admin DB Title (e.g. "GoogleCPC") —
    NOT the channel-level classification above. Per direct instruction,
    this powers a per-source Free/Paid display; it is deliberately
    conservative and returns None (no match) far more often than a match,
    since most GA4 source/mediums (especially long-tail Referral) have no
    Title counterpart at all, and this must never guess.

    known_titles_lower: {title.lower(): original_title} — the exact set of
    Titles present in whichever conversion sheet(s) are loaded. Only exact
    matches against this set are ever returned.

    Returns the matched Title (original casing) or None.
    """
    if not source_medium:
        return None
    parts = source_medium.strip().split(" / ")
    source = parts[0].strip().lower()
    medium = parts[1].strip().lower() if len(parts) > 1 else ""

    # Literal aliases — mirrors EXACT_MAP's reverse direction for the cases
    # that aren't themselves domains.
    if source == "(direct)" and medium in ("(none)", ""):
        if "direct" in known_titles_lower:
            return known_titles_lower["direct"]
    if source == "google" and medium == "cpc":
        if "googlecpc" in known_titles_lower:
            return known_titles_lower["googlecpc"]
    if source == "bing" and medium == "cpc":
        if "bingcpc" in known_titles_lower:
            return known_titles_lower["bingcpc"]

    # Domain-based exact match — the GA4 source segment, stripped of a
    # leading "www.", matched case-insensitively against a real Title.
    host = source[4:] if source.startswith("www.") else source
    if host in known_titles_lower:
        return known_titles_lower[host]

    # GA4 trims well-known search engines to a bare name with no TLD for
    # organic search (e.g. source "google" in "google / organic"), while
    # the Admin DB records the full domain ("google.com"). Restricted to
    # medium == "organic" ONLY — bug found in QA: "bing / ppc" and the
    # malformed "google / cpc/" tracking artifact both have bare source
    # "bing"/"google" too, and were wrongly inheriting bing.com's/
    # google.com's entire organic Free/Paid count just because the source
    # word matched, even though "cpc"/"ppc" is not "organic". A given
    # Title's numbers must only ever attach to the ONE row that's actually
    # organic search for it, never to unrelated same-source rows.
    if medium == "organic" and "." not in host:
        for title_lower, original in known_titles_lower.items():
            if "." in title_lower and title_lower.split(".")[0] == host:
                return original

    return None

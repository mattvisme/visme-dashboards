"""
scripts/shared/slack_client.py
Minimal Slack Incoming Webhook client shared by the anomaly-check scripts.

Deliberately dependency-free (uses urllib, not `requests`) so the anomaly
workflows don't need an extra pip install step.
"""

import json
import urllib.error
import urllib.request


def post_to_slack(webhook_url: str, text: str, blocks: list | None = None, timeout: int = 30) -> None:
    """
    POST a message to a Slack Incoming Webhook.

    Args:
        webhook_url: The full https://hooks.slack.com/... URL (SLACK_WEBHOOK_URL secret).
        text:        Fallback/plain text shown in notifications and when blocks can't render.
        blocks:      Optional Slack Block Kit blocks for rich formatting.
        timeout:     Request timeout in seconds.

    Raises:
        ValueError if webhook_url is empty.
        RuntimeError if Slack rejects the payload or the request otherwise fails.
    """
    if not webhook_url:
        raise ValueError("SLACK_WEBHOOK_URL is not set")

    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status != 200:
                raise RuntimeError(f"Slack webhook returned HTTP {resp.status}: {body}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Slack webhook HTTP error {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Slack webhook network error: {exc.reason}") from exc


def build_anomaly_message(check_name: str, title: str, findings: list[dict], severity: str = "warning") -> tuple[str, list]:
    """
    Build a Slack Block Kit payload for a batch of anomaly findings from one check.

    Args:
        check_name: Short identifier of the check that fired, e.g. "check_traffic_anomaly.py".
        title:      Human-readable headline, e.g. "Website Traffic Anomaly".
        findings:   List of finding dicts, each with:
                       "summary": one-line description of the anomaly
                       "fields":  list of (label, value) tuples with metric/baseline/% change/etc.
        severity:   "critical" | "warning" | "info" — controls the emoji.

    Returns:
        (fallback_text, blocks) — pass directly to post_to_slack(url, text=fallback_text, blocks=blocks).
    """
    emoji = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "⚠️")
    header_text = f"{emoji} {title}"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text[:150]}},
    ]
    for finding in findings:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{finding['summary']}*"},
        })
        mrkdwn_fields = [
            {"type": "mrkdwn", "text": f"*{label}:*\n{value}"}
            for label, value in finding.get("fields", [])
        ]
        if mrkdwn_fields:
            blocks.append({"type": "section", "fields": mrkdwn_fields[:10]})
        blocks.append({"type": "divider"})

    # Drop the trailing divider.
    if blocks and blocks[-1].get("type") == "divider":
        blocks.pop()

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"Check: `{check_name}` · {len(findings)} finding(s)"}],
    })

    fallback = f"{header_text} — {len(findings)} finding(s) from {check_name}"
    return fallback, blocks

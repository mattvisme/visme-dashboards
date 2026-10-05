"""
scripts/shared/fibbler_client.py
Minimal MCP (streamable HTTP) client for Fibbler's remote MCP server.

Fibbler has no REST API, only MCP at https://app.fibbler.co/mcp.
Auth: FIBBLER_API_KEY env var, sent as `Authorization: Bearer <key>`.

Usage:
    fib = Fibbler()
    data = fib.call("get_campaign_performance", {"time_period": "30d"})
"""

import json
import os
import time
import urllib.error
import urllib.request

MCP_URL = os.environ.get("FIBBLER_MCP_URL", "https://app.fibbler.co/mcp")
PROTOCOL = "2025-03-26"


class Fibbler:
    def __init__(self):
        key = os.environ.get("FIBBLER_API_KEY", "").strip()
        if not key:
            raise EnvironmentError(
                "FIBBLER_API_KEY is not set. Add it to GitHub repository secrets."
            )
        self._key = key
        self._session = None
        self._id = 0
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "visme-dashboards", "version": "1.0"},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _post(self, body: dict):
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        req = urllib.request.Request(
            MCP_URL, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            self._session = resp.headers.get("Mcp-Session-Id") or self._session
            raw = resp.read().decode("utf-8")
            ctype = resp.headers.get("Content-Type", "")
        if not raw.strip():
            return None
        if "text/event-stream" in ctype:
            # Take the last SSE `data:` event carrying a JSON-RPC response.
            msg = None
            for line in raw.splitlines():
                if line.startswith("data:"):
                    try:
                        cand = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if "result" in cand or "error" in cand:
                        msg = cand
            return msg
        return json.loads(raw)

    def _rpc(self, method: str, params: dict, retries: int = 3):
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        for attempt in range(retries):
            try:
                msg = self._post(body)
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(
                    f"Fibbler MCP HTTP {exc.code} on {method}: "
                    f"{exc.read().decode('utf-8', errors='replace')[:300]}"
                ) from exc
        if msg is None or "error" in msg:
            raise RuntimeError(f"Fibbler MCP error on {method}: {(msg or {}).get('error')}")
        return msg["result"]

    def call(self, tool: str, args: dict) -> dict:
        """Call a Fibbler tool and return its parsed JSON payload."""
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise RuntimeError(f"Fibbler tool {tool} failed: {text[:300]}")
        return json.loads(text)

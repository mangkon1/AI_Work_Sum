"""
Cursor agent  (type: cursor) — placeholder with optional webhook mode.

Cursor does not (yet) expose a public local HTTP API that accepts a prompt and
returns the agent's answer, so this adapter works in one of two ways:

1. Webhook mode — if `webhook_url` is configured, the router POSTs
       {"message", "context", "from_agent", "target"}
   to that URL (e.g. a small bridge script / a Cursor background-agent wrapper /
   n8n flow you own) and returns its reply (same parsing rules as type: http).

2. Not configured — returns a clear "not configured" error (HTTP 503).

Cursor itself normally talks TO the router as an MCP *client* (see README:
.cursor/mcp.json) — that direction works fully today.

    agents:
      cursor:
        type: cursor
        webhook_url: ${CURSOR_WEBHOOK_URL}
        headers: { Authorization: "Bearer ${CURSOR_WEBHOOK_TOKEN}" }
"""
from __future__ import annotations

import os
from typing import Any

from .http_agent import HttpAgent


class CursorAgent(HttpAgent):
    type_name = "cursor"
    url_key = "webhook_url"

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        config = dict(config or {})
        if not (config.get("webhook_url") or config.get("url")) and os.environ.get("CURSOR_WEBHOOK_URL"):
            config["webhook_url"] = os.environ["CURSOR_WEBHOOK_URL"]
        super().__init__(name, config)

    def not_configured_message(self) -> str:
        return (f"Agent '{self.name}' (Cursor) is not configured: Cursor has no public prompt API. "
                f"Set agents.{self.name}.webhook_url in config.yaml (or CURSOR_WEBHOOK_URL in .env) "
                f"to a bridge endpoint that accepts JSON {{message, context, from_agent}}.")

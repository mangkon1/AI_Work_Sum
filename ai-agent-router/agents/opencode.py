"""
OpenCode agent  (type: opencode).

OpenCode is the *main* agent: normally it calls the router through MCP. This
adapter covers the reverse direction (another agent delegating work TO OpenCode).

Modes
-----
mode: server   (default when base_url is set)
    Uses the HTTP API of `opencode serve` (https://opencode.ai/docs/server/):
        POST {base_url}/session                    -> {"id": ...}
        POST {base_url}/session/{id}/message       body {"parts":[{"type":"text","text":...}], ...}
    The text parts of the reply are joined and returned.
    Optional HTTP basic auth (OPENCODE_SERVER_PASSWORD / OPENCODE_SERVER_USERNAME).

mode: webhook
    Generic JSON POST to `url` (same as type: http).

No base_url / url  ->  clear "not configured" error (HTTP 503).

    agents:
      opencode:
        type: opencode
        base_url: http://127.0.0.1:4096       # `opencode serve --port 4096`
        password: ${OPENCODE_SERVER_PASSWORD} # optional
        agent: build                          # optional opencode agent name
        model: { providerID: xai, modelID: grok-4.7 }   # optional
        reuse_session: true                   # keep one session across calls
        timeout: 600
"""
from __future__ import annotations

import os
from typing import Any

from .base import AgentError, AgentNotConfiguredError
from .http_agent import HttpAgent


class OpenCodeAgent(HttpAgent):
    type_name = "opencode"

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        config = dict(config or {})
        config.setdefault("timeout", 600)  # coding tasks can be slow
        super().__init__(name, config)
        self.base_url: str = str(self.config.get("base_url") or os.environ.get("OPENCODE_BASE_URL") or "").rstrip("/")
        self.mode: str = str(self.config.get("mode") or ("server" if self.base_url else "webhook")).lower()
        self.username: str = str(self.config.get("username") or os.environ.get("OPENCODE_SERVER_USERNAME") or "opencode")
        self.password: str = str(self.config.get("password") or os.environ.get("OPENCODE_SERVER_PASSWORD") or "")
        self.oc_agent: str | None = self.config.get("agent")
        self.model: dict[str, str] | None = self.config.get("model")
        self.reuse_session: bool = bool(self.config.get("reuse_session", True))
        self.directory: str | None = self.config.get("directory")
        self._session_id: str | None = None

    def is_configured(self) -> bool:
        return bool(self.base_url) if self.mode == "server" else bool(self.url)

    def not_configured_message(self) -> str:
        return (f"Agent '{self.name}' (OpenCode) is not configured: run `opencode serve --port 4096` and set "
                f"agents.{self.name}.base_url: http://127.0.0.1:4096 in config.yaml (or OPENCODE_BASE_URL in .env).")

    def _auth(self) -> tuple[str, str] | None:
        return (self.username, self.password) if self.password else None

    def _params(self) -> dict[str, str]:
        return {"directory": self.directory} if self.directory else {}

    async def _get_session(self, from_agent: str) -> str:
        if self.reuse_session and self._session_id:
            return self._session_id
        resp = await self._request("POST", f"{self.base_url}/session", auth=self._auth(), params=self._params(),
                                   json={"title": f"AI Agent Router: from {from_agent}"})
        try:
            sid = resp.json()["id"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AgentError(f"{self.name}: unexpected /session reply: {resp.text[:300]}",
                             code="bad_upstream_payload") from exc
        if self.reuse_session:
            self._session_id = sid
        return sid

    async def invoke(self, message: str, context: dict[str, Any] | None = None,
                     from_agent: str = "opencode") -> str:
        if self.mode != "server":
            return await super().invoke(message, context, from_agent)  # webhook / generic HTTP
        if not self.base_url:
            raise AgentNotConfiguredError(self.not_configured_message())

        text = message
        ctx = self.context_as_text(context)
        if ctx:
            text += f"\n\n---\nContext (JSON) from agent '{from_agent}':\n{ctx}"
        body: dict[str, Any] = {"parts": [{"type": "text", "text": text}]}
        if self.oc_agent:
            body["agent"] = self.oc_agent
        if self.model:
            body["model"] = self.model

        sid = await self._get_session(from_agent)
        try:
            resp = await self._request("POST", f"{self.base_url}/session/{sid}/message",
                                       json=body, auth=self._auth(), params=self._params())
        except AgentError as exc:
            # stale session (e.g. opencode restarted) -> retry once with a fresh session
            if exc.upstream_status == 404 and self.reuse_session:
                self._session_id = None
                sid = await self._get_session(from_agent)
                resp = await self._request("POST", f"{self.base_url}/session/{sid}/message",
                                           json=body, auth=self._auth(), params=self._params())
            else:
                raise
        try:
            data = resp.json()
            parts = data.get("parts") or []
        except (ValueError, AttributeError) as exc:
            raise AgentError(f"{self.name}: unexpected message reply: {resp.text[:300]}",
                             code="bad_upstream_payload") from exc
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(t for t in texts if t).strip()

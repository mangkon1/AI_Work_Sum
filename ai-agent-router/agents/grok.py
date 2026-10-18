"""
Grok agent  (type: grok) — xAI Chat Completions API.

    POST {base_url}/chat/completions        (default base_url: https://api.x.ai/v1)
    Authorization: Bearer $XAI_API_KEY

config.yaml:
    agents:
      grok:
        type: grok
        api_key: ${XAI_API_KEY}        # or just set XAI_API_KEY in .env
        model: grok-4.7                # override with GROK_MODEL env var too
        timeout: 120
        temperature: 0.7               # optional
        max_tokens: 4096               # optional
        system_prompt: "You are Grok, a helpful coding agent ..."   # optional
"""
from __future__ import annotations

import os
from typing import Any

from .base import AgentError, AgentNotConfiguredError, BaseAgent

DEFAULT_MODEL = "grok-4.7"
DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_SYSTEM_PROMPT = (
    "You are Grok, one agent in a multi-agent system connected through the 'AI Agent Router'. "
    "Another AI agent is delegating a task to you. Answer the task directly and concisely; "
    "your reply is returned verbatim to the calling agent."
)


class GrokAgent(BaseAgent):
    type_name = "grok"

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, config)
        self.api_key: str = str(self.config.get("api_key") or os.environ.get("XAI_API_KEY") or "").strip()
        self.model: str = str(os.environ.get("GROK_MODEL") or self.config.get("model") or DEFAULT_MODEL)
        self.base_url: str = str(self.config.get("base_url") or os.environ.get("XAI_BASE_URL")
                                 or DEFAULT_BASE_URL).rstrip("/")
        self.system_prompt: str = str(self.config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)
        self.temperature = self.config.get("temperature")
        self.max_tokens = self.config.get("max_tokens")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def describe(self) -> dict[str, Any]:
        info = super().describe()
        info["model"] = self.model
        return info

    def build_messages(self, message: str, context: dict[str, Any] | None, from_agent: str) -> list[dict[str, str]]:
        system = f"{self.system_prompt}\n\nThe calling agent is: '{from_agent}'."
        ctx = self.context_as_text(context)
        if ctx:
            # context goes in as extra system text so the user turn stays the pure task
            system += f"\n\nAdditional context supplied by the caller (JSON):\n{ctx}"
        return [{"role": "system", "content": system}, {"role": "user", "content": message}]

    async def invoke(self, message: str, context: dict[str, Any] | None = None,
                     from_agent: str = "opencode") -> str:
        if not self.api_key:
            raise AgentNotConfiguredError(
                f"Agent '{self.name}' is not configured: set XAI_API_KEY in .env "
                f"(or agents.{self.name}.api_key in config.yaml)")

        body: dict[str, Any] = {
            "model": self.model,
            "messages": self.build_messages(message, context, from_agent),
            "stream": False,
        }
        if self.temperature is not None:
            body["temperature"] = float(self.temperature)
        if self.max_tokens is not None:
            body["max_tokens"] = int(self.max_tokens)

        resp = await self._request(
            "POST", f"{self.base_url}/chat/completions", json=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AgentError(f"{self.name}: unexpected xAI response: {resp.text[:300]}",
                             code="bad_upstream_payload") from exc
        if isinstance(content, list):  # defensive: content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return str(content or "")

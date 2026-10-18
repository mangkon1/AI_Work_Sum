"""
Grok agent  (type: grok, alias: xai) — xAI Chat Completions API (OpenAI-compatible).

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

from .base import AgentNotConfiguredError
from .openai_compat import OpenAICompatibleAgent

DEFAULT_MODEL = "grok-4.7"
DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_SYSTEM_PROMPT = (
    "You are Grok, one agent in a multi-agent system connected through the 'AI Agent Router'. "
    "Another AI agent is delegating a task to you. Answer the task directly and concisely; "
    "your reply is returned verbatim to the calling agent."
)


class GrokAgent(OpenAICompatibleAgent):
    type_name = "grok"

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        config = dict(config or {})
        config["api_key"] = str(config.get("api_key") or os.environ.get("XAI_API_KEY") or "").strip()
        config["model"] = os.environ.get("GROK_MODEL") or config.get("model") or DEFAULT_MODEL
        config["url"] = (config.get("url") or config.get("base_url") or os.environ.get("XAI_BASE_URL")
                         or DEFAULT_BASE_URL)
        config.setdefault("system_prompt", DEFAULT_SYSTEM_PROMPT)
        config["auth_type"] = config.get("auth_type") or "bearer"
        super().__init__(name, config)
        self.base_url = self.url.rsplit("/chat/completions", 1)[0]

    def is_configured(self) -> bool:
        return bool(self.api_key) and bool(self.url)

    def not_configured_message(self) -> str:
        return (f"Agent '{self.name}' is not configured: set XAI_API_KEY in .env "
                f"(or agents.{self.name}.api_key in config.yaml)")

    async def invoke(self, message: str, context: dict[str, Any] | None = None,
                     from_agent: str = "opencode") -> str:
        if not self.api_key:
            raise AgentNotConfiguredError(self.not_configured_message())
        return await super().invoke(message, context, from_agent)

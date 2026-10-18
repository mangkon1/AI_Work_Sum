"""
OpenAI-compatible Chat Completions agent  (type: openai-compatible, alias: openai)

Works with every provider that speaks the OpenAI /chat/completions format:
OpenAI, Google Gemini (OpenAI endpoint), OpenRouter, Groq, xAI, Ollama, LM Studio, vLLM ...

    agents:
      gpt:
        type: openai-compatible
        url: https://api.openai.com/v1          # base URL, or the full .../chat/completions URL
        api_key: ${GPT_API_KEY}                  # sent as "Authorization: Bearer ..." (omit for local servers)
        model: gpt-5.5
        system_prompt: "You are a careful reviewer"   # optional
        temperature: 0.2                              # optional
        max_tokens: 2048                              # optional
        headers: { HTTP-Referer: "https://example.com" }   # optional extra headers

Request : {"model", "messages": [{"role":"system",...}, {"role":"user", "content": <message>}], "stream": false}
Reply   : choices[0].message.content  (override with response_path)
"""
from __future__ import annotations

from typing import Any

from .base import AgentError, AgentNotConfiguredError
from .http_agent import HttpAgent, extract_field, _content_text


def chat_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    u = url.rstrip("/")
    if u.endswith("/chat/completions") or "?" in u:
        return u
    return u + "/chat/completions"


class OpenAICompatibleAgent(HttpAgent):
    type_name = "openai-compatible"
    default_base_url = ""
    default_response_path = "choices[0].message.content"

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        config = dict(config or {})
        if not config.get("url") and config.get("base_url"):
            config["url"] = config["base_url"]
        if not config.get("url") and self.default_base_url:
            config["url"] = self.default_base_url
        super().__init__(name, config)
        self.url = chat_url(self.url)
        self.response_path = self.response_path or self.default_response_path

    def is_configured(self) -> bool:
        return super().is_configured() and bool(self.model)

    def not_configured_message(self) -> str:
        if self.url and not self.model:
            return f"Agent '{self.name}' (type={self.type_name}) has no model: set 'model' in config.yaml / the GUI"
        if not self.url:
            return (f"Agent '{self.name}' (type={self.type_name}) is not configured: set 'url' "
                    f"(e.g. https://api.openai.com/v1)")
        return super().not_configured_message()

    def build_messages(self, message: str, context: dict[str, Any] | None, from_agent: str) -> list[dict[str, str]]:
        system = f"{self.system_prompt}\n\nThe calling agent is: '{from_agent}'."
        ctx = self.context_as_text(context)
        if ctx:
            # context goes in as extra system text so the user turn stays the pure task
            system += f"\n\nAdditional context supplied by the caller (JSON):\n{ctx}"
        return [{"role": "system", "content": system}, {"role": "user", "content": message}]

    def build_payload(self, message: str, context: dict[str, Any] | None, from_agent: str) -> Any:
        if self.body_template is not None:
            return super().build_payload(message, context, from_agent)
        body: dict[str, Any] = {**self.extra_body, "model": self.model,
                                "messages": self.build_messages(message, context, from_agent), "stream": False}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        return body

    def parse_response(self, text: str, content_type: str = "") -> str:
        import json
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise AgentError(f"{self.name}: upstream reply is not JSON: {text[:300]}",
                             code="bad_upstream_payload") from exc
        value = extract_field(data, self.response_path)
        if value is None:
            raise AgentError(f"{self.name}: field '{self.response_path}' not found in upstream reply: {text[:300]}",
                             code="bad_upstream_payload")
        return _content_text(value)

    async def invoke(self, message: str, context: dict[str, Any] | None = None,
                     from_agent: str = "opencode") -> str:
        if self.missing_env:
            raise AgentNotConfiguredError(self.not_configured_reason())
        return await super().invoke(message, context, from_agent)

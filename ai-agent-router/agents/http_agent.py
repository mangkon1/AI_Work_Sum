"""
Generic HTTP agent  (type: http)

POSTs JSON to a URL and returns the response text. This makes adding a new
agent a config-only change:

    agents:
      my-agent:
        type: http
        url: http://127.0.0.1:9000/invoke
        headers: { Authorization: "Bearer ${MY_AGENT_TOKEN}" }
        response_field: response      # dotted path inside the JSON reply (optional)

Request body sent upstream:
    {"message": ..., "context": {...}, "from_agent": ..., "target": <agent name>}

Reply parsing: if `response_field` is set it is used (dotted path, e.g. "data.text");
otherwise the first of response / output / text / content / message / result is
used; a non-JSON reply is returned as plain text.
"""
from __future__ import annotations

from typing import Any

from .base import AgentError, AgentNotConfiguredError, BaseAgent

_DEFAULT_FIELDS = ("response", "output", "text", "content", "message", "result", "answer")


def extract_field(data: Any, path: str | None) -> Any:
    """Return the value at a dotted path ("a.b.0.c"); None if missing."""
    if not path:
        return None
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


class HttpAgent(BaseAgent):
    type_name = "http"
    #: config key holding the URL (CursorAgent uses "webhook_url")
    url_key = "url"

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, config)
        self.url: str = str(self.config.get(self.url_key) or self.config.get("url") or "").strip()
        self.method: str = str(self.config.get("method", "POST")).upper()
        self.headers: dict[str, str] = {str(k): str(v) for k, v in (self.config.get("headers") or {}).items()}
        self.response_field: str | None = self.config.get("response_field")
        # extra static fields merged into the JSON body
        self.extra_body: dict[str, Any] = dict(self.config.get("extra_body") or {})

    def is_configured(self) -> bool:
        return bool(self.url)

    def not_configured_message(self) -> str:
        return (f"Agent '{self.name}' (type={self.type_name}) is not configured: "
                f"set '{self.url_key}' for it in config.yaml")

    def build_payload(self, message: str, context: dict[str, Any] | None, from_agent: str) -> dict[str, Any]:
        return {**self.extra_body, "message": message, "context": context or {},
                "from_agent": from_agent, "target": self.name}

    async def invoke(self, message: str, context: dict[str, Any] | None = None,
                     from_agent: str = "opencode") -> str:
        if not self.url:
            raise AgentNotConfiguredError(self.not_configured_message())
        payload = self.build_payload(message, context, from_agent)
        resp = await self._request(self.method, self.url, json=payload, headers=self.headers)
        return self.parse_response(resp.text, resp.headers.get("content-type", ""))

    def parse_response(self, text: str, content_type: str = "") -> str:
        try:
            import json
            data = json.loads(text)
        except ValueError:
            return text  # plain-text reply
        if self.response_field:
            value = extract_field(data, self.response_field)
            if value is None:
                raise AgentError(f"{self.name}: field '{self.response_field}' not found in upstream reply",
                                 code="bad_upstream_payload")
            return value if isinstance(value, str) else _dump(value)
        if isinstance(data, dict):
            for key in _DEFAULT_FIELDS:
                if key in data and data[key] is not None:
                    v = data[key]
                    return v if isinstance(v, str) else _dump(v)
        if isinstance(data, str):
            return data
        return _dump(data)


def _dump(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)

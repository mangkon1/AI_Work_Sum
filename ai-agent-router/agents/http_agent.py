"""
Generic HTTP agent  (type: http)  — any JSON (or text) API, configured without code.

    agents:
      my-agent:
        type: http
        url: http://127.0.0.1:9000/invoke
        method: POST                       # POST (default) / PUT / PATCH / GET
        headers: { X-Team: "ai", Authorization: "Bearer ${MY_AGENT_TOKEN}" }
        auth_type: bearer                  # none | bearer | header   (optional, uses api_key)
        auth_header: x-api-key             # header name when auth_type = header
        api_key: ${MY_AGENT_KEY}           # secret lives in .env, config.yaml only holds the reference
        body_template:                     # optional - default body = {message, context, from_agent, target}
          model: "{model}"
          input: "{prompt}"
        response_path: choices[0].message.content   # optional (dotted path, [i] list index)
        timeout: 120

Placeholders inside body_template string values
    {message} {prompt} {context} {context_json} {from_agent} {target} {model} {system_prompt}
    {temperature} {max_tokens}
    * a value that is EXACTLY one placeholder keeps its JSON type ({context} -> object,
      {temperature} -> number); if that value is empty the key is dropped.
    * inside a longer string the value is inserted as text (JSON-safe - the body is built
      as data, never by string concatenation).
    {prompt} = message + the context as JSON text (handy for APIs with only one text field).

Reply parsing: `response_path` (alias `response_field`) if set; otherwise the first of
response / output / text / content / message / result / answer; non-JSON reply = plain text.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .base import AgentError, AgentNotConfiguredError, BaseAgent

_DEFAULT_FIELDS = ("response", "output", "text", "content", "message", "result", "answer")
PLACEHOLDERS = ("message", "prompt", "context", "context_json", "context_text", "from_agent", "target",
                "model", "system_prompt", "temperature", "max_tokens")
_PH = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")
_PATH_TOKEN = re.compile(r"\[(-?\d+)\]|\[[\"']([^\"']*)[\"']\]|([^.\[\]]+)")
_DROP = object()

DEFAULT_SYSTEM_PROMPT = (
    "You are '{name}', one agent in a multi-agent system connected through the 'AI Agent Router'. "
    "Another AI agent is delegating a task to you. Answer the task directly and concisely; "
    "your reply is returned verbatim to the calling agent."
)


def parse_path(path: str) -> list[str | int]:
    """'choices[0].message.content' / 'content.0.text' / '$.a["b c"]' -> tokens."""
    path = path.strip()
    if path.startswith("$"):
        path = path[1:].lstrip(".")
    out: list[str | int] = []
    for m in _PATH_TOKEN.finditer(path):
        idx, quoted, word = m.groups()
        if idx is not None:
            out.append(int(idx))
        elif quoted is not None:
            out.append(quoted)
        elif word is not None:
            out.append(int(word) if re.fullmatch(r"-?\d+", word) else word)
    return out


def extract_field(data: Any, path: str | None) -> Any:
    """Value at a path like 'choices[0].message.content' or 'a.b.0.c'; None if missing."""
    if not path:
        return None
    cur = data
    for part in parse_path(path):
        if isinstance(part, int):
            if isinstance(cur, list) and -len(cur) <= part < len(cur):
                cur = cur[part]
            elif isinstance(cur, dict) and str(part) in cur:
                cur = cur[str(part)]
            else:
                return None
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def render_template(tpl: Any, values: dict[str, Any]) -> Any:
    """Fill {placeholders} in every string of a JSON-like structure (see module doc)."""
    if isinstance(tpl, str):
        m = _PH.fullmatch(tpl.strip())
        if m:
            v = values.get(m.group(1))
            return _DROP if v is None or v == "" else v
        return _PH.sub(lambda mm: _as_text(values.get(mm.group(1))), tpl)
    if isinstance(tpl, list):
        return [x for x in (render_template(v, values) for v in tpl) if x is not _DROP]
    if isinstance(tpl, dict):
        out = {}
        for k, v in tpl.items():
            r = render_template(v, values)
            if r is not _DROP:
                out[k] = r
        return out
    return tpl


def _num(value: Any, kind: type) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return kind(value)
    except (TypeError, ValueError):
        return None


class HttpAgent(BaseAgent):
    type_name = "http"
    #: config key holding the URL (CursorAgent uses "webhook_url")
    url_key = "url"

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, config)
        self.url: str = str(self.config.get(self.url_key) or self.config.get("url") or "").strip()
        self.method: str = str(self.config.get("method") or "POST").upper()
        self.headers: dict[str, str] = {str(k): str(v) for k, v in (self.config.get("headers") or {}).items()
                                        if str(k).strip()}
        self.response_path: str | None = (self.config.get("response_path") or self.config.get("response_field")
                                          or None)
        self.response_field = self.response_path  # backwards compatible name
        # extra static fields merged into the JSON body
        self.extra_body: dict[str, Any] = dict(self.config.get("extra_body") or {})
        self.body_template: Any = self.config.get("body_template")
        if isinstance(self.body_template, str) and self.body_template.strip():
            try:
                self.body_template = json.loads(self.body_template)
            except ValueError:
                pass  # plain-text template, sent as text/plain
        elif isinstance(self.body_template, str):
            self.body_template = None
        self.api_key: str = str(self.config.get("api_key") or "").strip()
        default_auth = "bearer" if self.api_key else "none"
        self.auth_type: str = str(self.config.get("auth_type") or default_auth).lower()
        self.auth_header: str = str(self.config.get("auth_header") or "x-api-key")
        self.model: str = str(self.config.get("model") or "")
        self.system_prompt: str = str(self.config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT.format(name=name))
        self.temperature = _num(self.config.get("temperature"), float)
        self.max_tokens = _num(self.config.get("max_tokens"), int)

    # ------------------------------------------------------------- status
    def is_configured(self) -> bool:
        if not self.url:
            return False
        if self.auth_type in ("bearer", "header") and not self.api_key:
            return False
        return True

    def not_configured_message(self) -> str:
        if self.url and self.auth_type in ("bearer", "header") and not self.api_key:
            return f"Agent '{self.name}' (type={self.type_name}) has no API key: set it in the GUI or in .env"
        return (f"Agent '{self.name}' (type={self.type_name}) is not configured: "
                f"set '{self.url_key}' for it in config.yaml")

    def describe(self) -> dict[str, Any]:
        info = super().describe()
        if self.model:
            info["model"] = self.model
        if self.url:
            info["url"] = re.sub(r"([?&](?:key|api_key|token)=)[^&]+", r"\1***", self.url)
        return info

    # ------------------------------------------------------------- request
    def request_headers(self) -> dict[str, str]:
        h = dict(self.headers)
        if self.api_key and self.auth_type == "bearer":
            h["Authorization"] = f"Bearer {self.api_key}"
        elif self.api_key and self.auth_type == "header":
            h[self.auth_header] = self.api_key
        return h

    def template_values(self, message: str, context: dict[str, Any] | None, from_agent: str) -> dict[str, Any]:
        ctx_text = self.context_as_text(context)
        prompt = message + (f"\n\n---\nContext (JSON) from agent '{from_agent}':\n{ctx_text}" if ctx_text else "")
        return {"message": message, "prompt": prompt, "context": context or {}, "context_json": ctx_text,
                "context_text": ctx_text, "from_agent": from_agent, "target": self.name, "model": self.model,
                "system_prompt": self.system_prompt, "temperature": self.temperature,
                "max_tokens": self.max_tokens}

    def build_payload(self, message: str, context: dict[str, Any] | None, from_agent: str) -> Any:
        if self.body_template is not None:
            body = render_template(self.body_template, self.template_values(message, context, from_agent))
            if isinstance(body, dict) and self.extra_body:
                body = {**self.extra_body, **body}
            return body
        return {**self.extra_body, "message": message, "context": context or {},
                "from_agent": from_agent, "target": self.name}

    async def invoke(self, message: str, context: dict[str, Any] | None = None,
                     from_agent: str = "opencode") -> str:
        if self.missing_env:
            raise AgentNotConfiguredError(self.not_configured_reason())
        if not self.is_configured():
            raise AgentNotConfiguredError(self.not_configured_message())
        payload = self.build_payload(message, context, from_agent)
        kwargs: dict[str, Any] = {"headers": self.request_headers()}
        if self.method == "GET":
            if isinstance(payload, dict):
                kwargs["params"] = {k: _as_text(v) for k, v in payload.items()}
        elif isinstance(payload, (dict, list)):
            kwargs["json"] = payload
        else:
            kwargs["content"] = _as_text(payload).encode("utf-8")
            kwargs["headers"].setdefault("Content-Type", "text/plain; charset=utf-8")
        resp = await self._request(self.method, self.url, **kwargs)
        return self.parse_response(resp.text, resp.headers.get("content-type", ""))

    def parse_response(self, text: str, content_type: str = "") -> str:
        try:
            data = json.loads(text)
        except ValueError:
            return text  # plain-text reply
        if self.response_path:
            value = extract_field(data, self.response_path)
            if value is None:
                raise AgentError(f"{self.name}: field '{self.response_path}' not found in upstream reply: "
                                 f"{text[:300]}", code="bad_upstream_payload")
            return _content_text(value)
        if isinstance(data, dict):
            for key in _DEFAULT_FIELDS:
                if key in data and data[key] is not None:
                    return _content_text(data[key])
        if isinstance(data, str):
            return data
        return _dump(data)


def _content_text(value: Any) -> str:
    """str as-is; a list of content parts ([{type:text,text:..}]) joined; anything else as JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and all(isinstance(p, dict) and "text" in p for p in value):
        return "".join(str(p.get("text") or "") for p in value)
    return _dump(value)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)

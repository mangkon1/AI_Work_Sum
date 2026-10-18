"""
Base classes shared by every agent adapter.

Every agent:
  * has a unique `name` (the value callers put in "target")
  * implements `async invoke(message, context, from_agent) -> str`
  * raises `AgentError` (or a subclass) on failure — the router maps it to an HTTP status
"""
from __future__ import annotations

import abc
import json
import logging
from typing import Any

import httpx


class AgentError(Exception):
    """Raised by an agent when it cannot produce a response.

    status_code is the HTTP status the router returns to the caller:
      502 = upstream returned an error / bad payload (default)
      503 = agent is not configured / disabled
      504 = upstream timed out
    """

    def __init__(self, message: str, *, status_code: int = 502, upstream_status: int | None = None,
                 code: str = "upstream_error") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.upstream_status = upstream_status
        self.code = code


class AgentNotConfiguredError(AgentError):
    """Agent exists in the registry but is missing required settings (URL, API key ...)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=503, code="agent_not_configured")


class BaseAgent(abc.ABC):
    """Abstract async agent."""

    #: registry type name (e.g. "grok", "http") — set by subclasses
    type_name: str = "base"

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        self.name = name
        self.config: dict[str, Any] = dict(config or {})
        self.enabled: bool = bool(self.config.get("enabled", True))
        self.description: str = str(self.config.get("description", ""))
        self.timeout: float = float(self.config.get("timeout", 120))
        self.log = logging.getLogger(f"router.agent.{name}")
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ API
    @abc.abstractmethod
    async def invoke(self, message: str, context: dict[str, Any] | None = None,
                     from_agent: str = "opencode") -> str:
        """Send `message` to the agent and return its textual response."""

    def is_configured(self) -> bool:
        """True when the agent has everything it needs to run (shown in /health)."""
        return True

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type_name,
            "enabled": self.enabled,
            "configured": self.is_configured(),
            "description": self.description,
        }

    # -------------------------------------------------------------- helpers
    @property
    def client(self) -> httpx.AsyncClient:
        """Lazily-created shared AsyncClient for this agent."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=10.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """HTTP request with uniform error mapping (timeouts -> 504, transport/HTTP errors -> 502)."""
        try:
            resp = await self.client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise AgentError(f"{self.name}: upstream timeout after {self.timeout:.0f}s ({url})",
                             status_code=504, code="upstream_timeout") from exc
        except httpx.HTTPError as exc:
            raise AgentError(f"{self.name}: cannot reach upstream {url}: {exc.__class__.__name__}: {exc}",
                             code="upstream_unreachable") from exc
        if resp.status_code >= 400:
            body = resp.text[:500]
            raise AgentError(f"{self.name}: upstream HTTP {resp.status_code}: {body}",
                             upstream_status=resp.status_code)
        return resp

    @staticmethod
    def context_as_text(context: dict[str, Any] | None) -> str:
        """Pretty JSON of the context (empty string when no context)."""
        if not context:
            return ""
        try:
            return json.dumps(context, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            return str(context)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} enabled={self.enabled}>"

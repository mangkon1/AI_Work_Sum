"""
Router core — shared by the FastAPI endpoints AND the MCP tools (in-process).

Responsibilities
  * build the agent registry from Settings.agents
  * authenticate API keys (key -> bound agent name)
  * route a request to exactly ONE named target (never broadcast)
  * timing, request ids, logging, error mapping
"""
from __future__ import annotations

import hmac
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agents import AgentError, BaseAgent, create_agent
from config import Settings

log = logging.getLogger("router.core")


class RouterError(Exception):
    """Error with an HTTP status, raised by the router before/after calling an agent."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class Caller:
    """Who is calling (resolved from the API key)."""
    key_id: str                 # short, non-secret fingerprint for logs
    bound_agent: str | None     # agent name the key belongs to (None = any)
    transport: str = "http"     # http | mcp-http | mcp-stdio


@dataclass
class InvokeResult:
    target: str
    from_agent: str
    response: str
    status: str
    elapsed_ms: float
    request_id: str
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"target": self.target, "from_agent": self.from_agent, "response": self.response,
                "status": self.status, "elapsed_ms": self.elapsed_ms, "request_id": self.request_id}


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class Router:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.agents, self.load_errors = self._build_agents(settings)
        self._retired: list[BaseAgent] = []
        log.info("Registered agents: %s", ", ".join(f"{a.name}({a.type_name})" for a in self.agents.values()) or "-")

    @staticmethod
    def _build_agents(settings: Settings) -> tuple[dict[str, BaseAgent], dict[str, str]]:
        agents: dict[str, BaseAgent] = {}
        errors: dict[str, str] = {}
        for name, cfg in settings.agents.items():
            try:
                agents[name] = create_agent(name, cfg)
            except Exception as exc:  # bad config for one agent must not kill the server
                errors[name] = str(exc)
                log.error("Failed to create agent '%s': %s", name, exc)
        return agents, errors

    def reload(self, settings: Settings) -> None:
        """Hot-swap the agent registry + keys (called by the GUI after saving; thread-safe enough:
        the dict references are replaced atomically, in-flight calls keep their old agent object).
        Host/port changes still need a server restart."""
        agents, errors = self._build_agents(settings)
        old = list(self.agents.values())
        self.settings, self.agents, self.load_errors = settings, agents, errors
        self._retired.extend(old)
        log.info("Reloaded agents: %s", ", ".join(f"{a.name}({a.type_name})" for a in agents.values()) or "-")

    async def _close_retired(self) -> None:
        retired, self._retired = self._retired, []
        for agent in retired:
            try:
                await agent.aclose()
            except Exception:  # pragma: no cover
                pass

    # ------------------------------------------------------------- auth
    @property
    def auth_required(self) -> bool:
        return bool(self.settings.api_keys) or not self.settings.allow_anonymous

    def authenticate(self, api_key: str | None, transport: str = "http") -> Caller:
        """Return the Caller for an API key or raise RouterError(401)."""
        keys = self.settings.api_keys
        if not keys:
            if self.settings.allow_anonymous:
                return Caller(key_id="anonymous", bound_agent=None, transport=transport)
            raise RouterError(401, "auth_not_configured",
                              "No API keys configured on the router. Set ROUTER_API_KEYS in .env "
                              "(or auth.api_keys in config.yaml).")
        if not api_key:
            log.warning("auth rejected (%s): missing API key", transport,
                        extra={"event": "auth_rejected", "transport": transport, "reason": "missing"})
            raise RouterError(401, "missing_api_key", "Missing X-API-Key header")
        for key, agent in keys.items():
            # constant-time comparison
            if hmac.compare_digest(key.encode(), api_key.encode()):
                return Caller(key_id=f"key:{agent or 'any'}:{key[:3]}***", bound_agent=agent, transport=transport)
        log.warning("auth rejected (%s): invalid API key", transport,
                    extra={"event": "auth_rejected", "transport": transport, "reason": "invalid"})
        raise RouterError(401, "invalid_api_key", "Invalid API key")

    # ------------------------------------------------------------- listing
    def list_agents(self) -> list[dict[str, Any]]:
        out = [a.describe() for a in self.agents.values()]
        out += [{"name": n, "type": "?", "enabled": False, "configured": False, "error": e}
                for n, e in self.load_errors.items()]
        return out

    # ------------------------------------------------------------- invoke
    def resolve_from_agent(self, caller: Caller, from_agent: str | None) -> str:
        """Validate `from_agent` against the key's bound agent (403 on mismatch)."""
        fa = (from_agent or "").strip() or caller.bound_agent or self.settings.default_from_agent
        if caller.bound_agent and fa != caller.bound_agent:
            raise RouterError(403, "from_agent_mismatch",
                              f"This API key belongs to agent '{caller.bound_agent}' "
                              f"and cannot act as from_agent='{fa}'")
        return fa

    async def invoke(self, *, target: str, message: str, context: dict[str, Any] | None,
                     from_agent: str | None, caller: Caller, request_id: str | None = None) -> InvokeResult:
        rid = request_id or new_request_id()
        t0 = time.perf_counter()
        if self._retired:
            await self._close_retired()
        target = (target or "").strip()
        try:
            fa = self.resolve_from_agent(caller, from_agent)
            agent = self._validate(target, message, context, fa)
        except RouterError as exc:
            # rejected before reaching an agent (404 unknown target, 400 self-call, 403 ...)
            who = (from_agent or "").strip() or caller.bound_agent or self.settings.default_from_agent
            log.warning("invoke %s -> %s rejected %s: %s", who, target or "?", exc.status_code,
                        exc.message, extra={"request_id": rid, "event": "invoke_fail",
                                            "from_agent": who,
                                            "target": target or "?", "transport": caller.transport,
                                            "status_code": exc.status_code, "error": exc.message,
                                            "code": exc.code})
            raise
        extra: dict[str, Any] = {"request_id": rid}

        # structured fields (event/from_agent/target/...) are used by the GUI log panel
        extra.update(from_agent=fa, target=target, transport=caller.transport)
        log.info("invoke %s -> %s via %s (%s, %d chars)", fa, target, caller.transport, caller.key_id,
                 len(message), extra={**extra, "event": "invoke_start"})
        try:
            response = await agent.invoke(message, context or {}, fa)
        except AgentError as exc:
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            log.warning("invoke %s -> %s FAILED %s in %.1fms: %s", fa, target, exc.status_code, elapsed,
                        exc.message, extra={**extra, "event": "invoke_fail", "elapsed_ms": elapsed,
                                            "status_code": exc.status_code, "error": exc.message,
                                            "code": exc.code})
            raise RouterError(exc.status_code, exc.code, exc.message) from exc
        except Exception as exc:  # unexpected bug in an adapter
            log.exception("invoke %s -> %s crashed", fa, target,
                          extra={**extra, "event": "invoke_fail", "status_code": 502, "error": str(exc),
                                 "code": "agent_crashed"})
            raise RouterError(502, "agent_crashed", f"{target}: {exc.__class__.__name__}: {exc}") from exc

        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        log.info("invoke %s -> %s OK in %.1fms (%d chars)", fa, target, elapsed, len(response),
                 extra={**extra, "event": "invoke_ok", "elapsed_ms": elapsed})
        return InvokeResult(target=target, from_agent=fa, response=response, status="ok",
                            elapsed_ms=elapsed, request_id=rid)

    def _validate(self, target: str, message: str, context: dict[str, Any] | None, fa: str) -> BaseAgent:
        """Request checks before an agent is called. Returns the target agent or raises RouterError."""
        if not target:
            raise RouterError(400, "missing_target", "'target' is required (routing is by explicit name only)")
        if not isinstance(message, str) or not message.strip():
            raise RouterError(400, "missing_message", "'message' must be a non-empty string")
        if len(message) > self.settings.max_message_chars:
            raise RouterError(413, "message_too_large",
                              f"message exceeds {self.settings.max_message_chars} characters")
        if context is not None and not isinstance(context, dict):
            raise RouterError(400, "bad_context", "'context' must be a JSON object")

        agent = self.agents.get(target)
        if agent is None:
            raise RouterError(404, "unknown_target",
                              f"Unknown target agent '{target}'. Registered: {', '.join(sorted(self.agents)) or '-'}")
        if not agent.enabled:
            raise RouterError(503, "agent_disabled", f"Agent '{target}' is disabled in config")
        if agent.missing_env:
            raise RouterError(503, "agent_not_configured", agent.not_configured_reason())
        if target == fa and not self.settings.allow_self_call:
            raise RouterError(400, "self_call", f"Agent '{fa}' cannot call itself (target == from_agent)")
        return agent

    async def aclose(self) -> None:
        await self._close_retired()
        for agent in self.agents.values():
            try:
                await agent.aclose()
            except Exception:  # pragma: no cover
                log.debug("error closing %s", agent.name, exc_info=True)

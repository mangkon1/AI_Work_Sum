"""
MCP server built into AI Agent Router (official `mcp` Python SDK).

Tools
  invoke_agent(target, message, context=None, from_agent=None)  -> route to ONE named agent
  delegate(...)                                                  -> alias of invoke_agent
  list_agents()                                                  -> registered agents

The tools call the same in-process `Router` as POST /invoke (no HTTP hop).

Transports
  * Streamable HTTP mounted into the FastAPI app at /mcp   (same port 8080)
  * SSE (legacy) at /sse  + /messages/                       (same port 8080)
  * stdio: `python main.py --mcp-stdio` / `AI-Agent-Router.exe --mcp-stdio`

SDK compatibility: mcp >= 2 (`MCPServer`, formerly FastMCP) is preferred;
mcp 1.x (`FastMCP`) is supported as a fallback.
"""
# NOTE: no `from __future__ import annotations` here — the SDK inspects the real
# annotation objects to detect the `Context` parameter of tools.
import json
import logging
from typing import Any, Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from config import APP_NAME, APP_VERSION, Settings
from router_core import Caller, Router, RouterError, new_request_id

try:  # mcp >= 2.0
    from mcp.server.mcpserver import Context, MCPServer as _ServerCls
    from mcp.server.mcpserver.exceptions import ToolError
    MCP_SDK_MAJOR = 2
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import Context, FastMCP as _ServerCls  # type: ignore[no-redef]
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore[no-redef]
    MCP_SDK_MAJOR = 1

log = logging.getLogger("router.mcp")

INSTRUCTIONS = (
    "AI Agent Router: send work to ANOTHER AI agent by explicit name. "
    "Call list_agents to see available targets, then invoke_agent(target=<name>, message=<task>). "
    "Only the named target runs — there is no broadcast. Put files/snippets/requirements in `context`."
)


def extract_api_key(headers: Any) -> Optional[str]:
    """X-API-Key header, or `Authorization: Bearer <key>` as a fallback."""
    if headers is None:
        return None
    key = headers.get("x-api-key")
    if key:
        return key.strip()
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def build_mcp_server(router: Router, settings: Settings):
    """Create the MCP server object and register the router tools."""
    if MCP_SDK_MAJOR >= 2:
        mcp = _ServerCls(name="agent-router", title=APP_NAME, version=APP_VERSION,
                         instructions=INSTRUCTIONS, log_level=settings.log_level)
    else:
        mcp = _ServerCls(name="agent-router", instructions=INSTRUCTIONS, log_level=settings.log_level,
                         host=settings.host, port=settings.port,
                         streamable_http_path=settings.mcp_path, sse_path="/sse", message_path="/messages/")

    def caller_from_ctx(ctx: Optional[Context]) -> Caller:
        """Resolve the caller: HTTP transports carry headers, stdio is a trusted local process."""
        request = None
        try:
            request = getattr(ctx.request_context, "request", None) if ctx is not None else None
        except Exception:  # outside a request (should not happen in a tool call)
            request = None
        headers = getattr(request, "headers", None)
        if headers is None:
            return Caller(key_id="stdio", bound_agent=None, transport="mcp-stdio")
        if not settings.mcp_require_auth:
            return Caller(key_id="mcp-noauth", bound_agent=None, transport="mcp-http")
        return router.authenticate(extract_api_key(headers), transport="mcp-http")

    async def _invoke(target: str, message: str, context: Optional[dict[str, Any]],
                      from_agent: Optional[str], ctx: Optional[Context]) -> dict[str, Any]:
        try:
            caller = caller_from_ctx(ctx)
            result = await router.invoke(target=target, message=message, context=context,
                                         from_agent=from_agent, caller=caller, request_id=new_request_id())
            return result.as_dict()
        except RouterError as exc:
            # surfaced to the MCP client as an isError tool result
            raise ToolError(f"[{exc.status_code} {exc.code}] {exc.message}") from exc

    @mcp.tool(description=(
        "Send a task/message to ONE other AI agent by explicit name and return its reply. "
        "target: agent name from list_agents (e.g. 'grok'). message: the task. "
        "context: optional JSON object with extra info (files, constraints). "
        "from_agent: your own agent name (default: the agent bound to your API key, else 'opencode')."))
    async def invoke_agent(target: str, message: str, context: Optional[dict[str, Any]] = None,
                           from_agent: Optional[str] = None, ctx: Context = None) -> dict[str, Any]:
        return await _invoke(target, message, context, from_agent, ctx)

    @mcp.tool(description="Alias of invoke_agent: delegate a task to ONE named agent and return its reply.")
    async def delegate(target: str, message: str, context: Optional[dict[str, Any]] = None,
                       from_agent: Optional[str] = None, ctx: Context = None) -> dict[str, Any]:
        return await _invoke(target, message, context, from_agent, ctx)

    @mcp.tool(description="List the agents registered in the router (name, type, enabled, configured).")
    async def list_agents(ctx: Context = None) -> dict[str, Any]:
        try:
            caller_from_ctx(ctx)  # auth check for HTTP transports
        except RouterError as exc:
            raise ToolError(f"[{exc.status_code} {exc.code}] {exc.message}") from exc
        return {"agents": router.list_agents()}

    return mcp


def build_mcp_routes(mcp, settings: Settings) -> list:
    """Return Starlette routes (streamable HTTP + optional SSE) ready to be added to the FastAPI app.

    IMPORTANT: the caller must run `mcp.session_manager.run()` inside the FastAPI lifespan,
    otherwise /mcp fails with "Task group is not initialized".
    """
    routes: list = []
    if MCP_SDK_MAJOR >= 2:
        http_app = mcp.streamable_http_app(streamable_http_path=settings.mcp_path, host=settings.host)
    else:
        http_app = mcp.streamable_http_app()
    routes.extend(http_app.routes)
    if settings.mcp_sse_enabled:
        if MCP_SDK_MAJOR >= 2:
            sse_app = mcp.sse_app(sse_path="/sse", message_path="/messages/", host=settings.host)
        else:
            sse_app = mcp.sse_app()
        routes.extend(sse_app.routes)
    return routes


class MCPAuthMiddleware:
    """Pure-ASGI middleware: X-API-Key (or Bearer) check for the MCP HTTP endpoints.

    Pure ASGI (not BaseHTTPMiddleware) so SSE / streaming responses are not buffered.
    """

    def __init__(self, app: ASGIApp, router: Router, prefixes: tuple[str, ...], enabled: bool = True) -> None:
        self.app = app
        self.router = router
        self.prefixes = prefixes
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (self.enabled and scope["type"] == "http"
                and any(scope["path"] == p or scope["path"].startswith(p + "/") for p in self.prefixes)):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            try:
                self.router.authenticate(extract_api_key(headers), transport="mcp-http")
            except RouterError as exc:
                log.debug("MCP auth rejected for %s: %s", scope["path"], exc.message)
                resp = JSONResponse({"error": {"code": exc.code, "message": exc.message}},
                                    status_code=exc.status_code)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def run_stdio(router: Router, settings: Settings) -> None:
    """Run the MCP server over stdio (stdout is reserved for JSON-RPC!)."""
    mcp = build_mcp_server(router, settings)
    log.info("MCP stdio server starting (mcp SDK v%d) with agents: %s",
             MCP_SDK_MAJOR, json.dumps([a["name"] for a in router.list_agents()]))
    try:
        await mcp.run_stdio_async()
    finally:
        await router.aclose()

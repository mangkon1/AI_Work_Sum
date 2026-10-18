"""
AI Agent Router — entrypoint.

    python main.py                       # no args  -> desktop GUI (Tkinter); server is started from the GUI
    python main.py --gui                 # force the GUI (may be combined with --config/--port/--host)
    python main.py --no-gui              # headless HTTP server on http://127.0.0.1:8080 (REST + MCP at /mcp)
    python main.py --headless            # same as --no-gui
    python main.py --port 9000 --host 0.0.0.0   # any server flag without --gui -> headless (as before)
    python main.py --config D:\\router\\config.yaml
    python main.py --mcp-stdio           # MCP over stdio (for OpenCode/Cursor "local" MCP command)

    AI-Agent-Router.exe [same flags]     # PyInstaller one-file build (build.bat)

Endpoints
    GET  /health            no auth   status + registered agents
    GET  /agents            X-API-Key list agents (detailed)
    POST /invoke            X-API-Key {"target","message","context","from_agent"}
    *    /mcp               X-API-Key MCP streamable HTTP
    GET  /sse, POST /messages/        MCP legacy SSE transport
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys
import time
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from config import (APP_NAME, APP_VERSION, Settings, app_base_dir, ensure_router_key, env_file_path, load_settings,
                    setup_logging)
from router_core import Router, RouterError, new_request_id

log = logging.getLogger("router.api")


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class InvokeRequest(BaseModel):
    target: str = Field(..., description="Name of the ONE agent that should handle the message")
    message: str = Field(..., description="Task / prompt for the target agent")
    context: dict[str, Any] = Field(default_factory=dict, description="Optional extra JSON context")
    from_agent: str | None = Field(default=None, description="Calling agent (default: key's agent or 'opencode')")


class InvokeResponse(BaseModel):
    target: str
    from_agent: str
    response: str
    status: str
    elapsed_ms: float
    request_id: str


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #
def create_app(settings: Settings, router: Router | None = None) -> FastAPI:
    router = router or Router(settings)
    mcp = None
    mcp_routes: list = []
    if settings.mcp_enabled:
        from mcp_server import build_mcp_routes, build_mcp_server
        mcp = build_mcp_server(router, settings)
        mcp_routes = build_mcp_routes(mcp, settings)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            if mcp is not None:
                # required for streamable HTTP: starts the session manager task group
                await stack.enter_async_context(mcp.session_manager.run())
            _log_startup(settings, router)
            try:
                yield
            finally:
                await router.aclose()
                log.info("shutdown complete")

    app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan,
                  description="Route work between AI agents by explicit target name (REST + MCP).")
    app.state.router = router
    app.state.settings = settings

    # ---------------------------------------------------------------- errors
    def error_response(request: Request, status: int, code: str, message: str,
                       extra: dict[str, Any] | None = None) -> JSONResponse:
        rid = getattr(request.state, "request_id", None) or new_request_id()
        body = {"status": "error", "error": {"code": code, "message": message}, "request_id": rid}
        body.update(extra or {})
        return JSONResponse(body, status_code=status, headers={"X-Request-ID": rid})

    @app.exception_handler(RouterError)
    async def _router_error(request: Request, exc: RouterError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message,
                              getattr(request.state, "error_extra", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(request, 422, "validation_error", "Invalid request body",
                              {"details": exc.errors()})

    # --------------------------------------------------------- request id mw
    # Pure ASGI (not @app.middleware / BaseHTTPMiddleware): BaseHTTPMiddleware wraps
    # streaming bodies and breaks the MCP SSE transport on disconnect.
    app.add_middleware(RequestIdMiddleware)

    def caller_for(request: Request):
        from mcp_server import extract_api_key  # local import keeps --no-mcp path light
        return router.authenticate(extract_api_key(request.headers), transport="http")

    # ---------------------------------------------------------------- routes
    @app.get("/", include_in_schema=False)
    async def index() -> HTMLResponse:
        # friendly landing page for people who click the URL in the GUI
        rows = "".join(
            f"<tr><td>{a['name']}</td><td>{a['type']}</td><td>{'พร้อมใช้' if a['enabled'] and a['configured'] else ('ปิด' if not a['enabled'] else 'ยังไม่ตั้งค่า')}</td></tr>"
            for a in router.list_agents())
        return HTMLResponse(
            "<!doctype html><html lang='th'><head><meta charset='utf-8'><title>AI Agent Router</title>"
            "<style>body{font-family:'Leelawadee UI',Tahoma,sans-serif;max-width:760px;margin:40px auto;color:#222}"
            "td,th{padding:4px 12px;border-bottom:1px solid #ddd}code{background:#f3f3f3;padding:2px 5px}</style></head><body>"
            f"<h2>✔ AI Agent Router กำลังทำงาน</h2><p>ตัวกลางให้ AI หลายตัวส่งงานหากันตามชื่อ (v{APP_VERSION})</p>"
            f"<p>MCP URL: <code>http://{settings.host}:{settings.port}{settings.mcp_path}</code> (ต้องส่ง header <code>X-API-Key</code>)</p>"
            f"<table><tr><th>Agent</th><th>ชนิด</th><th>สถานะ</th></tr>{rows}</table>"
            "<p><a href='/health'>/health</a> · <a href='/docs'>/docs (ทดลองเรียก API)</a></p></body></html>")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app": APP_NAME,
            "version": APP_VERSION,
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "auth_required": router.auth_required,
            "mcp": {"enabled": settings.mcp_enabled, "path": settings.mcp_path,
                    "sse": "/sse" if settings.mcp_sse_enabled else None},
            "agents": [{"name": a["name"], "type": a["type"], "enabled": a["enabled"],
                        "configured": a["configured"]} for a in router.list_agents()],
        }

    @app.get("/agents")
    async def list_agents(request: Request) -> dict[str, Any]:
        caller_for(request)
        return {"agents": router.list_agents()}

    @app.post("/invoke", response_model=InvokeResponse)
    async def invoke(body: InvokeRequest, request: Request) -> InvokeResponse:
        request.state.error_extra = {"target": body.target, "from_agent": body.from_agent}
        caller = caller_for(request)
        # resolved from_agent in error bodies (raises 403 on key/from_agent mismatch)
        request.state.error_extra["from_agent"] = router.resolve_from_agent(caller, body.from_agent)
        t0 = time.perf_counter()
        try:
            result = await router.invoke(target=body.target, message=body.message, context=body.context,
                                         from_agent=body.from_agent, caller=caller,
                                         request_id=request.state.request_id)
        except RouterError:
            request.state.error_extra["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            raise
        return InvokeResponse(**result.as_dict())

    # MCP routes last (so they never shadow REST routes)
    if mcp_routes:
        from mcp_server import MCPAuthMiddleware
        app.router.routes.extend(mcp_routes)
        prefixes = (settings.mcp_path, "/sse", "/messages") if settings.mcp_sse_enabled else (settings.mcp_path,)
        app.add_middleware(MCPAuthMiddleware, router=router, prefixes=prefixes,
                           enabled=settings.mcp_require_auth)
    return app


class RequestIdMiddleware:
    """Assign a request id (or reuse the caller's X-Request-ID) and echo it in the response headers."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = None
        for k, v in scope.get("headers", []):
            if k == b"x-request-id":
                rid = v.decode("latin-1")[:64]
                break
        rid = rid or new_request_id()
        scope.setdefault("state", {})["request_id"] = rid

        async def send_with_id(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(k.lower() == b"x-request-id" for k, _ in headers):
                    headers.append((b"x-request-id", rid.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_id)


def _log_startup(settings: Settings, router: Router) -> None:
    base = f"http://{settings.host}:{settings.port}"
    log.info("%s v%s listening on %s", APP_NAME, APP_VERSION, base)
    log.info("config: %s | .env: %s", settings.config_path or "(defaults)",
             ", ".join(map(str, settings.env_files)) or "-")
    if settings.mcp_enabled:
        log.info("MCP streamable HTTP: %s%s   SSE: %s", base, settings.mcp_path,
                 f"{base}/sse" if settings.mcp_sse_enabled else "off")
    if not settings.api_keys:
        if settings.allow_anonymous:
            log.warning("No API keys configured and allow_anonymous=true: ANYONE who can reach the port can invoke agents")
        else:
            log.warning("No API keys configured: /invoke and /mcp will reject every request. Set ROUTER_API_KEYS in .env")
    for a in router.list_agents():
        log.info("agent %-12s type=%-9s enabled=%s configured=%s", a["name"], a["type"], a["enabled"], a["configured"])


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="AI-Agent-Router", description=f"{APP_NAME} v{APP_VERSION}")
    p.add_argument("--host", help="bind host (default 127.0.0.1)")
    p.add_argument("--port", type=int, help="bind port (default 8080)")
    p.add_argument("--config", help="path to config.yaml (default: next to the EXE, then cwd)")
    p.add_argument("--mcp-stdio", action="store_true", help="run as an MCP server over stdio instead of HTTP")
    p.add_argument("--gui", action="store_true", help="open the desktop GUI (default when started without arguments)")
    p.add_argument("--no-gui", "--headless", dest="no_gui", action="store_true",
                   help="run the HTTP server without the GUI (console / service mode)")
    p.add_argument("--log-level", help="DEBUG / INFO / WARNING / ERROR")
    p.add_argument("--log-file", help="also write logs to this file")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return p.parse_args(argv)


def wants_gui(argv: list[str], args: argparse.Namespace) -> bool:
    """GUI if --gui, or if started with NO arguments at all (double-click). Everything else = headless."""
    if args.mcp_stdio or args.no_gui:
        return False
    if args.gui:
        return True
    if os.environ.get("ROUTER_NO_GUI", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    return len(argv) == 0


def gui_failed_notice(reason: str) -> None:
    """The GUI could not open -> we continue as a headless server. Never do that *invisibly*:
    on Windows the console was hidden by `--hide-console hide-early`, so show it again and pop up
    a message box; everywhere also print to stderr and write logs/startup-error.log."""
    msg = (f"[AI Agent Router] GUI unavailable ({reason}); starting headless server instead.\n"
           f"Settings / router key: {env_file_path()}")
    print(msg, file=sys.stderr)
    try:
        p = app_base_dir() / "logs" / "startup-error.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass
    if os.name == "nt":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW: the server is visible + closable
            ctypes.windll.user32.MessageBoxW(
                None, "เปิดหน้าต่างโปรแกรมไม่ได้ จึงทำงานแบบไม่มีหน้าต่าง (headless) แทน\n"
                      "ปิดโปรแกรมได้ที่หน้าต่าง console (กด Ctrl+C)\n\n" + msg, APP_NAME, 0x30)
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)

    if wants_gui(argv, args):
        try:
            import gui  # Tkinter; imported lazily so headless/stdio never needs Tk
            return gui.run_gui(create_app=create_app, config_path=args.config, host=args.host,
                               port=args.port, log_level=args.log_level)
        except ImportError as exc:  # includes gui.GuiUnavailable (no tkinter / no display)
            gui_failed_notice(str(exc))
    try:
        settings = load_settings(args.config)
    except Exception as exc:
        print(f"[AI Agent Router] config error: {exc}", file=sys.stderr)
        return 2
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if args.log_level:
        settings.log_level = args.log_level.upper()
    if args.log_file:
        settings.log_file = args.log_file

    setup_logging(settings.log_level, settings.log_file, stdio_mode=args.mcp_stdio)

    if not args.mcp_stdio and not settings.api_keys and not settings.allow_anonymous:
        # headless first run: create + persist a key instead of rejecting every request
        key, generated, warning = ensure_router_key(args.config)
        settings = load_settings(args.config) if not warning else settings
        if warning:
            settings.api_keys = {key: None}
            log.warning(warning)
        if generated:
            log.warning("Generated a router API key and saved it to %s - use it as X-API-Key: %s",
                        env_file_path(), key)
        if args.host:
            settings.host = args.host
        if args.port:
            settings.port = args.port

    if args.mcp_stdio:
        # stdout = JSON-RPC channel; every log line goes to stderr / file
        from mcp_server import run_stdio
        import anyio
        try:
            anyio.run(run_stdio, Router(settings), settings)
        except KeyboardInterrupt:
            pass
        return 0

    import uvicorn
    app = create_app(settings)
    config = uvicorn.Config(app, host=settings.host, port=settings.port, log_config=None,
                            log_level=settings.log_level.lower(), access_log=settings.log_level == "DEBUG")
    server = uvicorn.Server(config)
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

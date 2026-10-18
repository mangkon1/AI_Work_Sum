"""
Configuration loading for AI Agent Router.

Order of precedence (highest first):
  1. CLI flags (--host / --port / --config ...)  -> applied in main.py
  2. Environment variables (including values loaded from .env)
  3. config.yaml
  4. Built-in defaults

ไฟล์ config.yaml / .env จะถูกค้นหาจากโฟลเดอร์เดียวกับ EXE ก่อน (ตอน build ด้วย PyInstaller)
จากนั้นจึงค้นหาใน current working directory
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

APP_NAME = "AI Agent Router"
APP_VERSION = "1.0.0"

log = logging.getLogger("router.config")

# Agents that exist even when there is no config.yaml (zero-config start).
DEFAULT_AGENTS: dict[str, dict[str, Any]] = {
    "grok": {"type": "grok", "enabled": True, "description": "xAI Grok via api.x.ai"},
    "cursor": {"type": "cursor", "enabled": True, "description": "Cursor (webhook placeholder)"},
    "opencode": {"type": "opencode", "enabled": True, "description": "OpenCode (main agent, via `opencode serve`)"},
}


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def app_base_dir() -> Path:
    """Directory of the EXE when frozen (PyInstaller), otherwise of this source file."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    for d in (app_base_dir(), Path.cwd()):
        d = d.resolve()
        if d not in dirs:
            dirs.append(d)
    return dirs


def find_file(name: str) -> Path | None:
    """Return the first existing `name` next to the EXE / source, then in cwd."""
    for d in _candidate_dirs():
        p = d / name
        if p.is_file():
            return p
    return None


def load_env_files() -> list[Path]:
    """Load .env files (EXE dir first, then cwd). Real environment variables always win."""
    loaded: list[Path] = []
    for d in _candidate_dirs():
        p = d / ".env"
        if p.is_file():
            load_dotenv(p, override=False)
            loaded.append(p)
    return loaded


# --------------------------------------------------------------------------- #
# ${ENV_VAR} substitution
# --------------------------------------------------------------------------- #
# Supports ${VAR} and ${VAR:-default}
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def substitute_env(value: Any) -> Any:
    """Recursively replace ${VAR} / ${VAR:-default} in every string of a YAML structure."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [substitute_env(v) for v in value]
    if isinstance(value, dict):
        return {k: substitute_env(v) for k, v in value.items()}
    return value


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


# --------------------------------------------------------------------------- #
# Settings model
# --------------------------------------------------------------------------- #
@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8080
    log_level: str = "INFO"
    log_file: str | None = None

    # api key -> agent name bound to that key (None = key may act as any agent)
    api_keys: dict[str, str | None] = field(default_factory=dict)
    # If True and no keys are configured, requests are accepted without a key (NOT recommended)
    allow_anonymous: bool = False
    # If True, target == from_agent is allowed (default: rejected with 400)
    allow_self_call: bool = False
    default_from_agent: str = "opencode"
    max_message_chars: int = 200_000

    # MCP
    mcp_enabled: bool = True
    mcp_path: str = "/mcp"
    mcp_sse_enabled: bool = True
    mcp_require_auth: bool = True

    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    config_path: Path | None = None
    env_files: list[Path] = field(default_factory=list)


def parse_api_keys(raw: Any) -> dict[str, str | None]:
    """
    Accepts:
      - "key1:opencode,key2:cursor,key3"   (env var ROUTER_API_KEYS)
      - ["key1", "key2"]                   (YAML list of plain keys)
      - [{"key": "k1", "agent": "opencode"}, ...]
      - {"k1": "opencode", "k2": null}     (YAML mapping key -> agent)
    """
    keys: dict[str, str | None] = {}
    if raw is None:
        return keys
    if isinstance(raw, str):
        items: list[Any] = [x for x in (s.strip() for s in raw.split(",")) if x]
    elif isinstance(raw, dict):
        items = [{"key": k, "agent": v} for k, v in raw.items()]
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError(f"api_keys: unsupported format {type(raw).__name__}")

    for item in items:
        if isinstance(item, dict):
            key = str(item.get("key") or "").strip()
            agent = item.get("agent")
        else:
            text = str(item).strip()
            # "key:agent" — split at the LAST ':' so keys may contain ':' themselves
            if ":" in text:
                key, agent = text.rsplit(":", 1)
            else:
                key, agent = text, None
        key = key.strip()
        agent = (str(agent).strip() or None) if agent else None
        if key:
            keys[key] = agent
    return keys


def load_settings(config_path: str | None = None) -> Settings:
    """Load .env + config.yaml and build a Settings object."""
    env_files = load_env_files()

    # ---- locate config.yaml -------------------------------------------------
    path: Path | None = None
    explicit = config_path or os.environ.get("ROUTER_CONFIG")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")
    else:
        path = find_file("config.yaml") or find_file("config.yml")

    data: dict[str, Any] = {}
    if path:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: top level must be a mapping")
        data = substitute_env(data)

    server = data.get("server") or {}
    auth = data.get("auth") or {}
    mcp = data.get("mcp") or {}
    logging_cfg = data.get("logging") or {}

    s = Settings()
    s.config_path = path
    s.env_files = env_files

    # ---- config.yaml values ------------------------------------------------
    s.host = str(server.get("host", s.host))
    s.port = int(server.get("port", s.port))
    s.log_level = str(logging_cfg.get("level", s.log_level)).upper()
    s.log_file = logging_cfg.get("file") or None
    s.api_keys = parse_api_keys(auth.get("api_keys"))
    s.allow_anonymous = _as_bool(auth.get("allow_anonymous"), s.allow_anonymous)
    s.allow_self_call = _as_bool(data.get("allow_self_call"), s.allow_self_call)
    s.default_from_agent = str(data.get("default_from_agent", s.default_from_agent))
    s.max_message_chars = int(data.get("max_message_chars", s.max_message_chars))
    s.mcp_enabled = _as_bool(mcp.get("enabled"), s.mcp_enabled)
    s.mcp_path = str(mcp.get("path", s.mcp_path))
    s.mcp_sse_enabled = _as_bool(mcp.get("sse_enabled"), s.mcp_sse_enabled)
    s.mcp_require_auth = _as_bool(mcp.get("require_auth"), s.mcp_require_auth)

    agents = data.get("agents")
    if agents is None:
        agents = {k: dict(v) for k, v in DEFAULT_AGENTS.items()}
    if not isinstance(agents, dict):
        raise ValueError("config.yaml: 'agents' must be a mapping of name -> settings")
    s.agents = {str(k): (v or {}) for k, v in agents.items()}

    # ---- environment overrides --------------------------------------------
    env = os.environ
    if env.get("ROUTER_HOST"):
        s.host = env["ROUTER_HOST"]
    if env.get("ROUTER_PORT"):
        s.port = int(env["ROUTER_PORT"])
    if env.get("ROUTER_LOG_LEVEL"):
        s.log_level = env["ROUTER_LOG_LEVEL"].upper()
    if env.get("ROUTER_LOG_FILE"):
        s.log_file = env["ROUTER_LOG_FILE"]
    if env.get("ROUTER_API_KEYS"):
        # keys from env are merged on top of config.yaml keys
        s.api_keys.update(parse_api_keys(env["ROUTER_API_KEYS"]))
    if env.get("ROUTER_ALLOW_ANONYMOUS"):
        s.allow_anonymous = _as_bool(env["ROUTER_ALLOW_ANONYMOUS"])
    if env.get("ROUTER_MCP_REQUIRE_AUTH"):
        s.mcp_require_auth = _as_bool(env["ROUTER_MCP_REQUIRE_AUTH"])
    if "ROUTER_DEFAULT_FROM_AGENT" in env and env["ROUTER_DEFAULT_FROM_AGENT"]:
        s.default_from_agent = env["ROUTER_DEFAULT_FROM_AGENT"]

    if not s.mcp_path.startswith("/"):
        s.mcp_path = "/" + s.mcp_path
    s.mcp_path = s.mcp_path.rstrip("/") or "/mcp"
    return s


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
class _RequestIdFilter(logging.Filter):
    """Guarantee %(request_id)s exists on every record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


def setup_logging(level: str = "INFO", log_file: str | None = None, *, stdio_mode: bool = False) -> None:
    """
    Console + optional rotating file logging.
    IMPORTANT: console logs always go to *stderr*, so stdout stays clean for the
    MCP stdio transport (`--mcp-stdio`).
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level.upper())

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] [rid=%(request_id)s] %(message)s")
    flt = _RequestIdFilter()

    # Windows consoles (cp874/cp1252) cannot encode every character -> never crash on logging
    try:
        sys.stderr.reconfigure(errors="backslashreplace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console.addFilter(flt)
    root.addHandler(console)

    if log_file:
        p = Path(log_file)
        if not p.is_absolute():
            p = app_base_dir() / p
        p.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(p, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.addFilter(flt)
        root.addHandler(fh)

    # keep 3rd-party noise down
    for noisy in ("httpx", "httpcore", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if stdio_mode:
        # uvicorn is not used in stdio mode, but make sure nothing logs to stdout
        logging.getLogger("uvicorn").handlers.clear()

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
    """Directory of the EXE when frozen (PyInstaller), otherwise of this source file.

    Override with the ROUTER_HOME environment variable (portable setups / tests).
    """
    home = os.environ.get("ROUTER_HOME")
    if home:
        return Path(home).expanduser().resolve()
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


def config_write_path(config_path: str | Path | None = None) -> Path:
    """config.yaml the GUI reads/writes: --config / ROUTER_CONFIG, else an existing one, else next to the EXE."""
    explicit = config_path or os.environ.get("ROUTER_CONFIG")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return find_file("config.yaml") or find_file("config.yml") or (app_base_dir() / "config.yaml")


def env_file_path() -> Path:
    """The .env the GUI writes to: always the one next to the EXE / main.py."""
    return app_base_dir() / ".env"


def generate_api_key() -> str:
    """Strong random key (~256 bit), URL-safe so it can be pasted anywhere."""
    import secrets
    return "ar-" + secrets.token_urlsafe(32)


_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def atomic_write_text(path: Path, text: str) -> None:
    """Write a file so that a crash / hard kill / power loss never leaves it half-written.

    tmp file in the same folder -> flush + fsync -> os.replace (atomic on Windows and POSIX)
    -> fsync the directory (POSIX) so the rename itself is durable.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"{path.name}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    if os.name != "nt":
        try:
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass


def update_env_file(updates: dict[str, str | None], path: Path | None = None) -> Path:
    """Insert/replace KEY=value lines in .env, keeping comments and unrelated lines.

    A value of None removes the key. Also applies the values to os.environ so a
    restarted server (in the same process) sees them immediately.
    """
    path = path or env_file_path()
    for k, v in updates.items():
        if not _ENV_NAME.fullmatch(k):
            raise ValueError(f"invalid .env variable name: {k!r}")
        if v is not None and ("\n" in v or "\r" in v):
            raise ValueError(f"{k}: value must be a single line")
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    done: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _ENV_LINE.match(line)
        if m and m.group(1) in updates:
            key = m.group(1)
            if key in done:
                continue  # drop duplicates
            done.add(key)
            if updates[key] is not None:
                out.append(f"{key}={updates[key]}")
            continue
        out.append(line)
    new_keys = [k for k in updates if k not in done and updates[k] is not None]
    if new_keys:
        if out and out[-1].strip():
            out.append("")
        if not lines:
            out.append("# AI Agent Router settings (written by the GUI; safe to edit by hand)")
        out += [f"{k}={updates[k]}" for k in new_keys]
    tidy: list[str] = []
    for line in out:  # no runs of blank lines left behind by removed keys
        if not line.strip() and (not tidy or not tidy[-1].strip()):
            continue
        tidy.append(line)
    while tidy and not tidy[-1].strip():
        tidy.pop()
    atomic_write_text(path, "\n".join(tidy) + "\n")
    for k, v in updates.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return path


def _env_file_router_keys(path: Path) -> dict[str, str | None]:
    if not path.is_file():
        return {}
    try:
        from dotenv import dotenv_values
        raw = dotenv_values(path).get("ROUTER_API_KEYS") or ""
    except Exception:
        return {}
    return {k: a for k, a in parse_api_keys(raw).items() if not is_placeholder_key(k)}


def ensure_router_key(config_path: str | None = None) -> tuple[str, bool, str | None]:
    """Make sure a real router key exists AND is persisted in the .env next to the EXE.

    Called at startup (before any window/server), so a hard kill can never lose the key.
    Returns (main_key, generated_now, warning_or_None).
      * placeholder keys copied from .env.example ("change-me-...") count as "no key"
      * a key that only exists in the process environment or in a .env in the *current
        directory* is copied into the EXE-folder .env (that is the file users look for)
      * keys defined in config.yaml (auth.api_keys) are used as-is, nothing is written
    """
    load_env_files()
    target = env_file_path()
    env_keys = {k: a for k, a in parse_api_keys(os.environ.get("ROUTER_API_KEYS", "")).items()
                if not is_placeholder_key(k)}
    try:
        if env_keys:
            if not _env_file_router_keys(target):
                update_env_file({"ROUTER_API_KEYS": ",".join(f"{k}:{a}" if a else k for k, a in env_keys.items())},
                                target)
            return next(iter(env_keys)), False, None
        try:
            cfg_keys = load_settings(config_path).api_keys
        except Exception:
            cfg_keys = {}
        if cfg_keys:
            return next(iter(cfg_keys)), False, None
        key = generate_api_key()
        os.environ["ROUTER_API_KEYS"] = key  # works for this session even if the write below fails
        update_env_file({"ROUTER_API_KEYS": key}, target)
        return key, True, None
    except (OSError, ValueError) as exc:
        key = next(iter(env_keys), None) or os.environ.get("ROUTER_API_KEYS", "").split(",")[0].split(":")[0]
        if not key or is_placeholder_key(key):
            key = generate_api_key()
            os.environ["ROUTER_API_KEYS"] = key
        return key, not env_keys, (f"บันทึกไฟล์ {target} ไม่ได้ ({exc}) — กุญแจจะใช้ได้เฉพาะรอบนี้. "
                                   f"ย้ายโปรแกรมไปไว้ในโฟลเดอร์ที่เขียนไฟล์ได้ (เช่น Documents)")


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


def env_refs(value: Any) -> list[tuple[str, bool]]:
    """All ${VAR} references in a (nested) value as (name, has_default)."""
    out: list[tuple[str, bool]] = []
    if isinstance(value, str):
        out += [(m.group(1), m.group(2) is not None) for m in _ENV_PATTERN.finditer(value)]
    elif isinstance(value, list):
        for v in value:
            out += env_refs(v)
    elif isinstance(value, dict):
        for v in value.values():
            out += env_refs(v)
    return out


def missing_env_vars(value: Any) -> list[str]:
    """${VAR} references (without a :-default) whose variable is unset or empty."""
    seen: list[str] = []
    for name, has_default in env_refs(value):
        if not has_default and not os.environ.get(name, "").strip() and name not in seen:
            seen.append(name)
    return seen


#: values copied from .env.example / docs that must never count as a real key
PLACEHOLDER_KEY_PREFIXES = ("change-me", "changeme", "your-", "your_", "<", "xxx", "replace-me")


def is_placeholder_key(key: str) -> bool:
    k = key.strip().lower()
    return not k or k.startswith(PLACEHOLDER_KEY_PREFIXES)


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
    raw_agents = data.get("agents")
    missing_by_agent: dict[str, list[str]] = {}
    if isinstance(raw_agents, dict):
        for k, v in raw_agents.items():
            missing_by_agent[str(k)] = missing_env_vars(v or {})
            if isinstance(k, bool) or k is None:
                log.warning("config.yaml: an agent name was read as %r (YAML treats on/off/yes/no/true/false/null "
                            "as booleans) - put the name in quotes, e.g. \"off\":", k)
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
    s.agents = {}
    for k, v in agents.items():
        cfg = dict(v or {})
        cfg["_missing_env"] = missing_by_agent.get(str(k), [])
        s.agents[str(k)] = cfg

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

    placeholders = [k for k in s.api_keys if is_placeholder_key(k)]
    for k in placeholders:
        log.warning("ignoring placeholder API key '%s...' (copied from .env.example?) - set a real ROUTER_API_KEYS",
                    k[:10])
        s.api_keys.pop(k, None)

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
    # a --windowed / hidden-console process may have no stderr at all
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(fmt)
        console.addFilter(flt)
        root.addHandler(console)

    if log_file:
        p = Path(log_file)
        if not p.is_absolute():
            p = app_base_dir() / p
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(p, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        except OSError as exc:  # read-only folder, Controlled Folder Access ... -> keep running without a file log
            logging.getLogger("router.config").warning("cannot write log file %s: %s", p, exc)
        else:
            fh.setFormatter(fmt)
            fh.addFilter(flt)
            root.addHandler(fh)

    # keep 3rd-party noise down
    for noisy in ("httpx", "httpcore", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if stdio_mode:
        # uvicorn is not used in stdio mode, but make sure nothing logs to stdout
        logging.getLogger("uvicorn").handlers.clear()

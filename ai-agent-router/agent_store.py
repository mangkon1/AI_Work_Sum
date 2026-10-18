"""
Persist agents edited in the GUI.

* agents live in config.yaml (next to the EXE, created if missing) under `agents:`
* secrets NEVER go into config.yaml: the raw value is written to .env (e.g. CLAUDE_API_KEY=...)
  and config.yaml only gets the reference  api_key: ${CLAUDE_API_KEY}
* other sections of config.yaml are kept; the previous file is saved as config.yaml.bak
  (PyYAML cannot keep comments, so the .bak keeps a hand-written original)
"""
from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from config import DEFAULT_AGENTS, atomic_write_text, env_refs, update_env_file

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ENV_REF_ONLY = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}$")
SECRET_HEADER = re.compile(r"(auth|api[-_]?key|token|secret|password|passwd|key$)", re.I)
URL_SECRET = re.compile(r"([?&](?:key|api_key|apikey|token|access_token)=)([^&#]+)", re.I)
# well-known key shapes - a last line of defence for values typed into odd places
KNOWN_SECRET = re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,}|sk-ant-[A-Za-z0-9_\-]{16,}|xai-[A-Za-z0-9]{16,}|"
                          r"gsk_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_\-]{30,}|sk-or-[A-Za-z0-9_\-]{16,}|"
                          r"ghp_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,})\b")
SECRET_FIELDS = {"api_key": "API_KEY", "password": "PASSWORD", "token": "TOKEN"}


def validate_name(name: str) -> str | None:
    """None if OK, else a Thai error message."""
    if not name:
        return "กรุณาใส่ชื่อ"
    if not NAME_RE.match(name):
        return "ชื่อใช้ได้เฉพาะ a-z A-Z 0-9 - _ . (ขึ้นต้นด้วยตัวอักษร/ตัวเลข ไม่เกิน 64 ตัว ไม่มีช่องว่าง)"
    return None


def env_var_name(agent: str, suffix: str = "API_KEY") -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", agent).strip("_").upper() or "AGENT"
    if base[0].isdigit():
        base = "AGENT_" + base
    return f"{base}_{suffix}"


def is_env_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(ENV_REF_ONLY.match(value.strip()))


def ref_name(value: Any) -> str | None:
    if isinstance(value, str):
        refs = env_refs(value)
        if refs:
            return refs[0][0]
    return None


# --------------------------------------------------------------------------- yaml io
class _Dumper(yaml.SafeDumper):
    pass


def _str_rep(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_rep)


def load_raw_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def raw_agents(path: Path) -> dict[str, dict[str, Any]]:
    """Agents exactly as written in config.yaml (${VAR} references NOT substituted)."""
    data = load_raw_config(path)
    agents = data.get("agents")
    if agents is None:
        return copy.deepcopy(DEFAULT_AGENTS)
    return {str(k): dict(v or {}) for k, v in (agents or {}).items()}


def save_raw_config(path: Path, data: dict[str, Any]) -> None:
    text = ("# AI Agent Router - written by the GUI (the previous version is in config.yaml.bak).\n"
            "# Secrets are NOT stored here: ${NAME} values are read from .env next to this file.\n")
    text += yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, default_flow_style=False,
                      width=100)
    if path.is_file():
        try:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
    atomic_write_text(path, text)


# --------------------------------------------------------------------------- secret split
def split_secrets(name: str, cfg: dict[str, Any], secrets: dict[str, str] | None = None,
                  env_names: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    """Move every raw secret out of `cfg`.

    secrets   : {"api_key": "<typed value>"} - values typed into the GUI's secret fields
    env_names : {"api_key": "CLAUDE_API_KEY"} - .env variable to use (default NAME_API_KEY)
    Returns (cfg with ${VAR} references, {VAR: value} for .env).
    """
    cfg = copy.deepcopy(cfg)
    env: dict[str, str] = {}
    env_names = env_names or {}
    used: set[str] = set()

    def var_for(field: str, suffix: str) -> str:
        v = (env_names.get(field) or env_var_name(name, suffix)).strip()
        base, i = v, 2
        while v in used:
            v, i = f"{base}_{i}", i + 1
        used.add(v)
        return v

    # 1) dedicated secret fields (api_key / password / token)
    for field, suffix in SECRET_FIELDS.items():
        typed = (secrets or {}).get(field)
        current = cfg.get(field)
        if typed:
            if is_env_ref(typed):
                cfg[field] = typed.strip()
            else:
                var = var_for(field, suffix)
                env[var] = typed.strip()
                cfg[field] = "${" + var + "}"
        elif current and not is_env_ref(current) and "${" not in str(current):
            var = var_for(field, suffix)
            env[var] = str(current).strip()
            cfg[field] = "${" + var + "}"
        elif current and ref_name(current):
            used.add(ref_name(current))  # type: ignore[arg-type]
        elif not current and env_names.get(field) and (
                field != "api_key" or str(cfg.get("auth_type") or "").lower() in ("bearer", "header")):
            # key not typed yet: point at the .env variable so the agent shows "missing GROQ_API_KEY"
            cfg[field] = "${" + var_for(field, suffix) + "}"

    # 2) secret-looking headers  (Authorization: Bearer sk-..., x-api-key: ...)
    headers = cfg.get("headers")
    if isinstance(headers, dict):
        for h, v in list(headers.items()):
            v = "" if v is None else str(v)
            if not v or "${" in v or not SECRET_HEADER.search(str(h)):
                continue
            prefix, raw = "", v
            m = re.match(r"^(Bearer|Basic|Token)\s+(.+)$", v, re.I)
            if m:
                prefix, raw = m.group(1) + " ", m.group(2)
            var = var_for("header:" + str(h), re.sub(r"[^A-Za-z0-9]+", "_", str(h)).strip("_").upper())
            env[var] = raw.strip()
            headers[h] = prefix + "${" + var + "}"

    # 3) ?key=... in URLs
    for field in ("url", "webhook_url", "base_url"):
        u = cfg.get(field)
        if isinstance(u, str) and URL_SECRET.search(u):
            def _sub(m: re.Match) -> str:
                if "${" in m.group(2):
                    return m.group(0)
                var = var_for("url:" + m.group(1), "URL_KEY")
                env[var] = m.group(2)
                return m.group(1) + "${" + var + "}"
            cfg[field] = URL_SECRET.sub(_sub, u)

    # 4) last line of defence: any well-known key shape anywhere else
    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            def _rep(m: re.Match) -> str:
                var = var_for("scrub:" + m.group(0)[:8], "SECRET")
                env[var] = m.group(0)
                return "${" + var + "}"
            return KNOWN_SECRET.sub(_rep, value)
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        return value

    cfg = scrub(cfg)
    return cfg, env


def clean_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values / internal keys so config.yaml stays tidy."""
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        if str(k).startswith("_"):
            continue
        if v is None or (isinstance(v, (str, list, dict)) and not v and k != "enabled"):
            continue
        out[k] = v
    return out


def save_agent(path: Path, name: str, cfg: dict[str, Any], *, old_name: str | None = None,
               secrets: dict[str, str] | None = None, env_names: dict[str, str] | None = None,
               env_path: Path | None = None) -> dict[str, str]:
    """Add or update one agent. Secrets -> .env first, then config.yaml. Returns the .env updates."""
    err = validate_name(name)
    if err:
        raise ValueError(err)
    data = load_raw_config(path)
    agents = data.get("agents")
    agents = copy.deepcopy(DEFAULT_AGENTS) if agents is None else {str(k): v for k, v in (agents or {}).items()}
    if name != old_name and name in agents:
        raise ValueError(f"มี agent ชื่อ '{name}' อยู่แล้ว")
    clean, env_updates = split_secrets(name, cfg, secrets, env_names)
    clean = clean_cfg(clean)
    leak = KNOWN_SECRET.search(yaml.dump(clean, Dumper=_Dumper, allow_unicode=True))
    if leak:  # cannot happen after split_secrets - safety net
        raise ValueError(f"refusing to write a raw API key into {path.name}")
    if env_updates:
        update_env_file(env_updates, env_path)  # .env first: config.yaml never points at a missing secret
    new_agents: dict[str, Any] = {}
    replaced = False
    for k, v in agents.items():
        if old_name is not None and k == old_name:
            new_agents[name] = clean
            replaced = True
        elif k != name:
            new_agents[k] = v
    if not replaced:
        new_agents[name] = clean
    data["agents"] = new_agents
    save_raw_config(path, data)
    return env_updates


def delete_agent(path: Path, name: str, *, remove_secrets: bool = False, env_path: Path | None = None) -> list[str]:
    """Remove an agent from config.yaml. Optionally drop its ${VARS} from .env when nothing else uses them."""
    data = load_raw_config(path)
    agents = data.get("agents")
    agents = copy.deepcopy(DEFAULT_AGENTS) if agents is None else {str(k): v for k, v in (agents or {}).items()}
    if name not in agents:
        raise KeyError(name)
    removed = agents.pop(name) or {}
    data["agents"] = agents
    save_raw_config(path, data)
    dropped: list[str] = []
    if remove_secrets:
        still_used = {n for n, _ in env_refs(data)}
        dropped = [n for n, _ in env_refs(removed) if n not in still_used and n != "XAI_API_KEY"]
        dropped = list(dict.fromkeys(dropped))
        if dropped:
            update_env_file({n: None for n in dropped}, env_path)
    return dropped

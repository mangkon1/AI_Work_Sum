"""
Agent adapters + a lazy, dynamic agent-type registry.

New agent *instances* are added purely through config.yaml (`agents:` section,
`type:` = one of the keys below). New agent *types* can be registered at runtime
with `register_agent_type()` or referenced directly in config.yaml as
`type: "some.module:ClassName"`.
"""
from __future__ import annotations

import importlib
from typing import Any

from .base import AgentError, AgentNotConfiguredError, BaseAgent

# type name -> "module:Class"  (imported lazily on first use)
AGENT_TYPES: dict[str, str | type[BaseAgent]] = {
    "grok": "agents.grok:GrokAgent",
    "xai": "agents.grok:GrokAgent",
    "http": "agents.http_agent:HttpAgent",
    "webhook": "agents.http_agent:HttpAgent",
    "cursor": "agents.cursor:CursorAgent",
    "opencode": "agents.opencode:OpenCodeAgent",
}


def register_agent_type(type_name: str, cls: type[BaseAgent] | str) -> None:
    """Register (or override) an agent type."""
    AGENT_TYPES[type_name.lower()] = cls


def resolve_agent_class(type_name: str) -> type[BaseAgent]:
    spec: Any = AGENT_TYPES.get(type_name.lower(), type_name)
    if isinstance(spec, type):
        return spec
    if ":" not in str(spec):
        raise ValueError(f"Unknown agent type '{type_name}'. Known: {', '.join(sorted(AGENT_TYPES))}")
    module_name, _, cls_name = str(spec).partition(":")
    module = importlib.import_module(module_name)
    cls = getattr(module, cls_name, None)
    if not (isinstance(cls, type) and issubclass(cls, BaseAgent)):
        raise ValueError(f"'{spec}' is not a BaseAgent subclass")
    if type_name.lower() in AGENT_TYPES:
        AGENT_TYPES[type_name.lower()] = cls  # cache
    return cls


def create_agent(name: str, config: dict[str, Any]) -> BaseAgent:
    """Instantiate an agent from its config.yaml entry. Default type = agent name (grok/cursor/opencode) or http."""
    type_name = str(config.get("type") or (name if name.lower() in AGENT_TYPES else "http"))
    return resolve_agent_class(type_name)(name, config)


__all__ = ["AGENT_TYPES", "AgentError", "AgentNotConfiguredError", "BaseAgent",
           "create_agent", "register_agent_type", "resolve_agent_class"]

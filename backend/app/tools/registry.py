"""
Global tool registry with permission-based access control.

All @tool-decorated functions must be registered here with an explicit
ToolPermission.  Agents and the skills loader query this registry to
build their bound tool lists.

Usage
-----
    from app.tools.registry import TOOL_REGISTRY, ToolPermission

    # Get all tools available to the explore (read-only) agent
    explore_tools = TOOL_REGISTRY.get_tools_for_permission(ToolPermission.READONLY)

    # Get tools by skill tag
    analysis_tools = TOOL_REGISTRY.get_tools_for_skill("rdkit_analysis")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolPermission(str, Enum):
    READONLY = "readonly"    # Explore agent: read-only, no side-effects
    COMPUTE = "compute"      # Compute agent: heavy computation, write artifacts
    SYSTEM = "system"        # Internal only: task status, scratchpad


@dataclass
class ToolEntry:
    tool: Any                         # LangChain StructuredTool / @tool
    permission: ToolPermission
    skill_tags: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.tool.name


class ToolRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, ToolEntry] = {}

    def register(self, entry: ToolEntry) -> None:
        self._entries[entry.name] = entry

    def get(self, name: str) -> ToolEntry | None:
        return self._entries.get(name)

    def get_tools_for_permission(self, permission: ToolPermission) -> list[Any]:
        return [e.tool for e in self._entries.values() if e.permission == permission]

    def get_tools_for_skill(self, skill_tag: str) -> list[Any]:
        return [e.tool for e in self._entries.values() if skill_tag in e.skill_tags]

    def get_tools_by_names(self, names: list[str]) -> list[Any]:
        return [self._entries[n].tool for n in names if n in self._entries]

    def all_tools(self) -> list[Any]:
        return [e.tool for e in self._entries.values()]


# Singleton registry — populated by tool modules on import
TOOL_REGISTRY = ToolRegistry()


def _populate_registry() -> None:
    """Import all tool modules to trigger their self-registration."""
    # Import order intentional: system tools first (no deps), then domain tools
    from app.tools.system import task_status  # noqa: F401
    from app.tools.rdkit import chem_tools    # noqa: F401
    from app.tools.babel import prep          # noqa: F401


def get_populated_registry() -> ToolRegistry:
    """Return the registry after ensuring all tools are registered."""
    _populate_registry()
    return TOOL_REGISTRY

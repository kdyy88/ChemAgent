"""
skills/base.py — SkillManifest protocol definition.

A Skill is a named, versioned bundle that combines:
  - A set of tool_names referencing entries in tools/registry.py
  - A prompt fragment injected into the main agent's system prompt
  - A permission requirement
  - Optional session-scoped enable/disable flag

Per-session loading: the skills/loader.py reads the session's active skill
configuration and calls skills/loader.SessionSkillLoader.load(session_id)
to return the active tool list and assembled system prompt injection.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.tools.registry import ToolPermission


class SkillManifest(BaseModel):
    """Declarative descriptor for an installable agent skill."""

    name: str = Field(description="Unique skill identifier (snake_case)")
    version: str = Field(default="0.1.0", description="Semantic version")
    display_name: str = Field(description="Human-readable skill name (Chinese-friendly)")
    description: str = Field(
        description=(
            "LLM-readable description of what this skill enables. "
            "Used by the main agent's routing logic to decide when to activate."
        )
    )
    tool_names: list[str] = Field(
        description="Names of tools from tools/registry.py this skill activates"
    )
    prompt_fragment: str = Field(
        default="",
        description=(
            "System prompt fragment injected when this skill is active. "
            "Keep focused: describe domain context and when to use the skill's tools."
        ),
    )
    permission_required: ToolPermission = Field(
        default=ToolPermission.READONLY,
        description="Minimum permission level required to activate this skill",
    )
    enabled_by_default: bool = Field(
        default=True,
        description="Whether this skill is active in new sessions without explicit configuration",
    )

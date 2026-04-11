"""SkillManifest — per-session dynamic skill protocol.

A Skill packages a subset of tools + a system-prompt fragment into a
discoverable unit. At request time, ``skills.loader`` resolves which skills
are active for the current session and injects their tools and prompt
fragments into the main agent.

Design constraints
──────────────────
- Manifests are **pure data** — no runtime side-effects on import.
- ``tool_names`` must reference tool names registered in ``app.tools.registry``.
- ``prompt_fragment`` is appended to the main system prompt ONLY when the
  skill is active. Keep it concise (≤200 tokens recommended).
- ``permission_required`` is validated by the tool registry before
  ``tool_names`` are resolved; requesting a SYSTEM-tier tool from a
  READONLY-only skill raises ``PermissionError``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SkillTier(str, Enum):
    """Mirrors ``ChemToolTier`` — skills inherit the minimum required tier."""

    L1 = "L1"  # Read-only / lightweight (PubChem lookups, descriptor queries)
    L2 = "L2"  # Compute-heavy / state-mutating (3-D conformers, docking prep)


class SkillManifest(BaseModel):
    """Declarative descriptor for a single loadable skill."""

    name: str = Field(..., description="Unique skill identifier, e.g. 'rdkit_analysis'")
    version: str = Field("1.0.0", description="Semantic version for cache-busting")
    description: str = Field(
        ...,
        description="Human- and LLM-readable purpose statement used by the main "
        "agent to decide whether to activate this skill.",
    )
    tool_names: list[str] = Field(
        default_factory=list,
        description="Names of tools registered in app.tools.registry that this "
        "skill exposes. The registry enforces permission checks.",
    )
    prompt_fragment: str = Field(
        "",
        description="Short system-prompt fragment injected when the skill is active. "
        "Should describe what the skill does and any special constraints.",
    )
    tier_required: SkillTier = Field(
        SkillTier.L1,
        description="Minimum tool-tier permission required to load this skill.",
    )
    enabled_by_default: bool = Field(
        True,
        description="Whether the skill is active for new sessions unless overridden.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Free-form topic tags for future skill discovery / search.",
    )

    model_config = {"frozen": True}

    def as_registry_filter(self) -> dict[str, Any]:
        """Return kwargs suitable for ``tools.registry.get_tools_for_skill()``."""
        return {"tool_names": self.tool_names, "tier_required": self.tier_required}

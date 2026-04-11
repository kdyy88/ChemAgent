"""SkillManifest — per-session dynamic skill protocol.

A Skill packages a subset of tools + a system-prompt fragment into a
discoverable unit. At request time, ``skills.loader`` resolves which skills
are active for the current session and injects their tools and prompt
fragments into the main agent.

Progressive Disclosure
──────────────────────
- L1 (Discovery)  — ``name + description + when_to_use`` always present in the
  main agent system prompt.  ~100 tokens per skill, zero I/O per request.
- L2 (Activation) — Full ``SKILL.md`` body injected via ``tool_invoke_skill``
  when the agent decides to use the skill.  ~5 k tokens on demand.
- L3 (Reference)  — ``references/`` and ``scripts/`` files fetched by the agent
  via ``tool_read_skill_reference`` as needed.  No size limit.

Design constraints
──────────────────
- Manifests are **pure data** — no runtime side-effects on import.
- YAML Frontmatter in ``SKILL.md`` is the **single source of truth**.
  ``skills.loader.load_skill_catalogue()`` dynamically instantiates this class
  from the parsed frontmatter; no separate ``manifest.py`` files are used.
- ``tool_names`` must reference tool names registered in ``app.tools.registry``.
- ``prompt_fragment`` is retained for backward compatibility but superseded by
  the ``when_to_use`` / L2 SOP injection model.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SkillTier(str, Enum):
    """Mirrors ``ChemToolTier`` — skills inherit the minimum required tier."""

    L1 = "L1"  # Read-only / lightweight (PubChem lookups, descriptor queries)
    L2 = "L2"  # Compute-heavy / state-mutating (3-D conformers, docking prep)


class SkillArgument(BaseModel):
    """Declares a single input parameter a skill can accept."""

    name: str = Field(..., description="Parameter name, e.g. 'query' or 'smiles'.")
    description: str = Field(..., description="LLM-readable description of what to pass.")
    accepts: list[Literal["smiles", "artifact_id", "name", "text"]] = Field(
        default_factory=list,
        description="Semantic types this argument accepts.  Drives state-pointer selection.",
    )
    required: bool = Field(True, description="Whether the argument must be supplied.")

    model_config = {"frozen": True}


class SkillManifest(BaseModel):
    """Declarative descriptor for a single loadable skill.

    Instantiated dynamically from SKILL.md YAML frontmatter by
    ``skills.loader.load_skill_catalogue()``.  Never instantiate manually.
    """

    name: str = Field(..., description="Unique skill identifier, e.g. 'database-lookup'")
    version: str = Field("1.0.0", description="Semantic version for cache-busting")
    description: str = Field(
        ...,
        description="Human- and LLM-readable purpose statement (L1 catalogue).",
    )
    # ── Progressive Disclosure L1 fields ──────────────────────────────────────
    when_to_use: str = Field(
        "",
        description="Precise trigger condition shown in L1 catalogue.  Must include "
        "positive trigger and negative boundaries to prevent mis-routing.",
    )
    context: Literal["inline", "fork"] = Field(
        "inline",
        description=(
            "inline: tool_invoke_skill returns the processed SOP directly; the main "
            "agent continues its ReAct loop using tool_read_skill_reference + "
            "tool_fetch_chemistry_api to execute.  "
            "fork: tool_invoke_skill delegates to an isolated sub-agent via "
            "tool_run_sub_agent(mode='custom', required_skills=[skill_name])."
        ),
    )
    arguments: list[SkillArgument] = Field(
        default_factory=list,
        description="Declared input parameters; must include smiles/artifact_id "
        "accepts to enable state-pointer passing from parent agent.",
    )
    # ── Tool registry integration ──────────────────────────────────────────────
    tool_names: list[str] = Field(
        default_factory=list,
        description="Tools this skill uses (beyond the always-available fetch/ref tools).",
    )
    tier_required: SkillTier = Field(
        SkillTier.L1,
        description="Minimum tool-tier permission required to load this skill.",
    )
    # ── Legacy / compatibility fields ─────────────────────────────────────────
    prompt_fragment: str = Field(
        "",
        description="Deprecated: use when_to_use + L2 SOP injection instead.",
    )
    enabled_by_default: bool = Field(
        False,
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

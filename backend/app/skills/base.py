"""SkillManifest — Claude Code Compatible Dynamic Skill Protocol.

This module defines the Skill schema. To maintain compatibility with Claude Code's
official skill ecosystem and pass IDE linting, we adhere to the standard fields:
(name, description, argument-hint, user-invocable, etc.).

ChemAgent-specific configurations (context, strict arguments, tool_names) are
nested inside the `metadata` dictionary. We use @property decorators to expose
them transparently to the rest of the V4 backend.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SkillTier(str, Enum):
    """Mirrors ``ChemToolTier`` — skills inherit the minimum required tier."""
    L1 = "L1"  # Read-only / lightweight (PubChem lookups)
    L2 = "L2"  # Compute-heavy / state-mutating (3-D conformers)


class SkillArgument(BaseModel):
    """ChemAgent specific: Declares a single input parameter a skill can accept."""
    name: str = Field(..., description="Parameter name, e.g. 'query'.")
    description: str = Field(..., description="LLM-readable description.")
    accepts: list[Literal["smiles", "artifact_id", "name", "text"]] = Field(default_factory=list)
    required: bool = Field(True)

    model_config = {"frozen": True}


class SkillManifest(BaseModel):
    """Claude Code Compatible Declarative Descriptor for a loadable skill."""

    # ── 1. Claude Code Standard Fields (Passes IDE Linter) ────────────────────
    name: str = Field(..., description="Unique skill identifier, e.g. 'database-lookup'")
    description: str = Field(..., description="General purpose statement.")
    
    # Use Pydantic aliases to map YAML kebab-case to Python snake_case
    argument_hint: str | None = Field(None, alias="argument-hint")
    user_invocable: bool = Field(True, alias="user-invocable")
    disable_model_invocation: bool = Field(False, alias="disable-model-invocation")
    compatibility: list[str] | str | None = Field(None)
    license: str | None = Field(None)
    
    # ── 2. The Extension Hatch: metadata ──────────────────────────────────────
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Container for ChemAgent-specific configurations.",
    )

    model_config = {
        "frozen": True,
        "populate_by_name": True, # Allows constructing via alias or true name
        "extra": "ignore"         # Safely ignore unknown upstream fields
    }

    # ── 3. Property Proxies (Keeps V4 code unchanged!) ────────────────────────
    
    @property
    def when_to_use(self) -> str:
        """Fallback to description if when_to_use is not specified in metadata."""
        return self.metadata.get("when_to_use", self.description)

    @property
    def context(self) -> Literal["inline", "fork"]:
        return self.metadata.get("context", "inline")

    @property
    def arguments(self) -> list[SkillArgument]:
        """Dynamically instantiates SkillArgument models from metadata."""
        raw_args = self.metadata.get("arguments", [])
        return [SkillArgument(**a) if isinstance(a, dict) else a for a in raw_args]

    @property
    def tool_names(self) -> list[str]:
        return self.metadata.get("tool_names", [])

    @property
    def tier_required(self) -> SkillTier:
        return SkillTier(self.metadata.get("tier_required", "L1"))

    def as_registry_filter(self) -> dict[str, Any]:
        """Return kwargs suitable for ``tools.registry.get_tools_for_skill()``."""
        return {"tool_names": self.tool_names, "tier_required": self.tier_required}
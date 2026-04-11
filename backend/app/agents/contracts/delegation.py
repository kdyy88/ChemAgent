"""
agents/contracts/delegation.py — SubAgentDelegation contract.

Defines the typed payload for main_agent → sub_agent task delegation.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SubAgentName = Literal["explore", "compute", "plan", "custom"]


class SubAgentDelegation(BaseModel):
    """Typed delegation payload sent from main_agent to a sub_agent."""

    target_agent: SubAgentName = Field(description="Which sub-agent receives this task")
    task_description: str = Field(description="Human-readable task description")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Relevant context (active_smiles, prior results, etc.)",
    )
    skill_overrides: list[str] = Field(
        default_factory=list,
        description="Optional skill names to activate for this delegation (overrides session defaults)",
    )

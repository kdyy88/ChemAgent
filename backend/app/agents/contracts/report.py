"""
agents/contracts/report.py — SubAgent terminal report contract.

Defines the structured format sub_agents use to report completion back
to main_agent (XML-inspired, serialized to JSON for LangGraph state).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ReportStatus = Literal["completed", "failed", "needs_clarification"]


class SubAgentReport(BaseModel):
    """Structured terminal report from a sub_agent back to main_agent."""

    agent: str = Field(description="Name of the reporting sub-agent")
    status: ReportStatus
    summary: str = Field(description="Concise human-readable result summary (Chinese)")
    artifacts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Any artifacts produced (molecule images, SDF files, etc.)",
    )
    error: str | None = Field(
        default=None,
        description="Error message if status is 'failed'",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured data (e.g. SMILES updates, descriptor results)",
    )

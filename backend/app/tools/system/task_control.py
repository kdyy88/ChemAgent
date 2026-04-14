"""Task control tools -- class-based BaseChemTool contract.

  ToolAskHuman          -- HITL clarification gate
  ToolUpdateTaskStatus  -- report planner task progress
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.schemas.workflow import ValidationResult
from app.tools.base import ChemControlTool


# ── 1. tool_ask_human ─────────────────────────────────────────────────────────


class AskHumanInput(BaseModel):
    question: str = Field(
        ...,
        description=(
            "A single concise clarification question in Chinese. "
            "This is a terminal control action, not a data tool. "
            "If you call this tool, it must be the ONLY tool call in the current turn."
        ),
        min_length=4,
        max_length=160,
    )
    options: list[str] = Field(
        default_factory=list,
        description=(
            "Optional 2-4 short quick-reply choices in Chinese. "
            "Keep them mutually exclusive and user-facing."
        ),
        max_length=4,
    )


class ToolAskHuman(ChemControlTool[AskHumanInput, str]):
    """Terminal HITL control tool for requesting a user clarification."""

    name = "tool_ask_human"
    args_schema = AskHumanInput
    tier = "L1"
    max_result_size_chars = 1_000

    async def validate_input(
        self, args: AskHumanInput, context: dict
    ) -> ValidationResult:
        return ValidationResult(result=True)

    def call(self, args: AskHumanInput) -> str:
        """Pause execution and ask the scientist a clarifying question via the HITL gate."""
        return json.dumps(
            {
                "type": "clarification_requested",
                "question": args.question,
                "options": args.options,
            },
            ensure_ascii=False,
        )


tool_ask_human = ToolAskHuman().as_langchain_tool()


# ── 2. tool_update_task_status ────────────────────────────────────────────────


class UpdateTaskStatusInput(BaseModel):
    task_id: str = Field(description="Task id from the planner-generated task list")
    status: Literal["in_progress", "completed", "failed"] = Field(
        description="New execution status for the task"
    )
    summary: str | None = Field(
        default=None,
        description="Optional one-sentence summary of the task outcome or blocking reason",
    )


class ToolUpdateTaskStatus(ChemControlTool[UpdateTaskStatusInput, str]):
    """Report task execution progress for planner-generated task lists."""

    name = "tool_update_task_status"
    args_schema = UpdateTaskStatusInput
    tier = "L1"
    max_result_size_chars = 1_000

    async def validate_input(
        self, args: UpdateTaskStatusInput, context: dict
    ) -> ValidationResult:
        return ValidationResult(result=True)

    def call(self, args: UpdateTaskStatusInput) -> str:
        """Update the status and summary of a task in the current execution plan."""
        return json.dumps(
            {
                "status": "success",
                "task_id": args.task_id,
                "task_status": args.status,
                "summary": args.summary,
            },
            ensure_ascii=False,
        )


tool_update_task_status = ToolUpdateTaskStatus().as_langchain_tool()


# ── Catalog ───────────────────────────────────────────────────────────────────

ALL_TASK_CONTROL_TOOLS = [tool_ask_human, tool_update_task_status]


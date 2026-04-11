from __future__ import annotations

import json
from typing import Annotated, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class AskHumanArgs(BaseModel):
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
            "Keep them mutually exclusive and user-facing. "
            "Do not include analysis text, explanations, or more than four choices."
        ),
        max_length=4,
    )


@tool(args_schema=AskHumanArgs)
def tool_ask_human(
    question: Annotated[str, "The clarifying question to ask the user, in Chinese"],
    options: Annotated[list[str], "2-4 quick-reply options for the user to choose from (optional, Chinese)"] = [],
) -> str:
    """Terminal HITL control tool for requesting a user clarification."""
    return json.dumps({"type": "clarification_requested", "question": question, "options": options}, ensure_ascii=False)


@tool
def tool_update_task_status(
    task_id: Annotated[str, "Task id from the planner-generated task list"],
    status: Annotated[Literal["in_progress", "completed", "failed"], "New execution status for the task"],
    summary: Annotated[str | None, "Optional one-sentence summary of the task outcome or blocking reason"] = None,
) -> str:
    """Report task execution progress for planner-generated task lists."""
    return json.dumps({"status": "success", "task_id": task_id, "task_status": status, "summary": summary}, ensure_ascii=False)


ALL_SYSTEM_CONTROL_TOOLS = [tool_ask_human, tool_update_task_status]
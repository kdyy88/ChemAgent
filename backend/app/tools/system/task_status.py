"""Task status update tool for planner-generated task lists."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from langchain_core.tools import tool

@tool
def tool_update_task_status(
    task_id: Annotated[str, "Task id from the planner-generated task list"],
    status: Annotated[
        Literal["in_progress", "completed", "failed"],
        "New execution status for the task",
    ],
    summary: Annotated[
        str | None,
        "Optional one-sentence summary of the task outcome or blocking reason",
    ] = None,
) -> str:
    """Report task execution progress for planner-generated task lists.

    Call this tool before starting a planned task only when the task spans
    multiple rounds or needs explicit long-running UI feedback. For short tasks
    that will complete in the current work span, you may skip the initial
    ``in_progress`` update and report only the final ``completed``/``failed``
    status.
    When marking a task completed or failed, provide a short summary whenever
    there is a concrete stage result worth carrying forward. Only use task ids
    that already exist in the current plan.
    """
    return json.dumps(
        {
            "status": "success",
            "task_id": task_id,
            "task_status": status,
            "summary": summary,
        },
        ensure_ascii=False,
    )

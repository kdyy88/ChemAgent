"""
System tools: task status tracking and HITL (human-in-the-loop).

These are agent-internal control tools — not chemistry computation tools.
Registered with ToolPermission.SYSTEM so they are always available to all
agents that use the planner pattern.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field


# ── HITL pause tool ──────────────────────────────────────────────────────────

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
    options: Annotated[
        list[str],
        "2-4 quick-reply options for the user to choose from (optional, Chinese)",
    ] = [],
) -> str:
    """Terminal HITL control tool for requesting a user clarification.

    HARD RULES:
    1. This tool is not a chemistry data tool. It is a stop-and-wait control action.
    2. If you call this tool, it MUST be the only tool call in the current turn.
    3. After deciding to call this tool, stop immediately and do not call PubChem,
       web search, RDKit, Open Babel, or any other tool in the same turn.
    4. Ask exactly one concrete question. Do not bundle multiple questions.
    5. Only use this when progress is blocked by missing user input.

    WHEN TO USE — call this tool (and stop further tool calls in this turn) when:
    1. tool_pubchem_lookup returns found=false for the compound name, AND a backup
       English name also fails — ask the user for the correct name or a SMILES.
    2. The user's message is ambiguous (e.g. "帮我调研那个药" with no compound name).
    3. Multiple compounds share the same name and you cannot determine which one
       the user intends (e.g. "taxol" could refer to paclitaxel or docetaxel class).
    4. After two consecutive web searches return empty results — ask the user to
       confirm the compound spelling or provide an alternative name.

    DO NOT use this tool when you have sufficient information to proceed.
    After calling this tool, do NOT call any other tools — stop immediately."""
    return json.dumps(
        {
            "type": "clarification_requested",
            "question": question,
            "options": options,
        },
        ensure_ascii=False,
    )


# ── Task status tool ─────────────────────────────────────────────────────────

@tool
def tool_update_task_status(
    task_id: Annotated[str, "Task id from the planner-generated task list"],
    status: Annotated[
        Literal["in_progress", "completed", "failed"],
        "New execution status for the task",
    ],
) -> str:
    """Report task execution progress for planner-generated task lists.

    Call this tool before starting a planned task and again after finishing it.
    Only use task ids that already exist in the current plan.
    """
    return json.dumps(
        {
            "status": "success",
            "task_id": task_id,
            "task_status": status,
        },
        ensure_ascii=False,
    )


ALL_SYSTEM_TOOLS = [tool_ask_human, tool_update_task_status]

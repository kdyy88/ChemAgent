from __future__ import annotations

import json

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.agents.lg_tools import ALL_CHEM_TOOLS
from app.agents.postprocessors import TOOL_POSTPROCESSORS
from app.agents.state import ChemState
from app.agents.utils import (
    apply_active_smiles_update,
    dispatch_task_update,
    parse_tool_output,
    tool_result_to_text,
    update_tasks,
)

_TOOL_LOOKUP = {tool.name: tool for tool in ALL_CHEM_TOOLS}

# Tools that require explicit user approval before execution (Hard Breakpoint tier).
# Add tool names here to gate them behind the ApprovalCard UI.
HEAVY_TOOLS: frozenset[str] = frozenset()


async def tools_executor_node(state: ChemState, config: RunnableConfig) -> dict:
    last_message = state["messages"][-1]
    new_active_smiles = state.get("active_smiles")
    new_tasks = [dict(task) for task in state.get("tasks", [])]
    artifacts: list[dict] = []
    tool_messages: list[ToolMessage] = []
    tool_calls = list(getattr(last_message, "tool_calls", []))

    # ── Heavy-tool approval gate (Hard Breakpoint) ─────────────────────────
    # If any pending tool_call is registered in HEAVY_TOOLS, pause the graph
    # and wait for an explicit user decision before proceeding.
    heavy_call = next(
        (tc for tc in tool_calls if tc["name"] in HEAVY_TOOLS), None
    )
    if heavy_call is not None:
        resume_value = interrupt({
            "type": "approval_required",
            "tool_call_id": heavy_call["id"],
            "tool_name": heavy_call["name"],
            "args": heavy_call.get("args", {}),
        })

        action = (resume_value or {}).get("action", "approve") if isinstance(resume_value, dict) else "approve"

        if action == "reject":
            return {
                "messages": [
                    ToolMessage(
                        content=json.dumps(
                            {"status": "rejected", "message": "User rejected the execution of this tool. Please ask for new instructions or propose an alternative."},
                            ensure_ascii=False,
                        ),
                        tool_call_id=heavy_call["id"],
                        name=heavy_call["name"],
                    )
                ],
                "active_smiles": new_active_smiles,
                "artifacts": [],
                "tasks": new_tasks,
            }
        elif action == "modify":
            # Patch the tool_call args in-place before falling through to execution.
            patched_args = (resume_value or {}).get("args", heavy_call.get("args", {}))
            for tc in tool_calls:
                if tc["id"] == heavy_call["id"]:
                    tc["args"] = patched_args
                    break
        # action == "approve" → fall through unchanged

    ask_human_call = next((tool_call for tool_call in tool_calls if tool_call["name"] == "tool_ask_human"), None)
    if ask_human_call is not None:
        args = ask_human_call.get("args", {})
        resume_value = interrupt(
            {
                "question": str(args.get("question", "")),
                "options": list(args.get("options", [])),
                "called_tools": [
                    tool_call["name"]
                    for tool_call in tool_calls
                    if tool_call["name"] != "tool_ask_human"
                ],
                "known_smiles": new_active_smiles,
            }
        )

        if isinstance(resume_value, dict):
            answer = str(
                resume_value.get("answer")
                or resume_value.get("content")
                or resume_value
            )
        else:
            answer = str(resume_value)

        tool_messages.append(
            ToolMessage(
                content=json.dumps(
                    {
                        "status": "clarification_received",
                        "message": "用户已提供澄清信息",
                        "question": str(args.get("question", "")),
                        "answer": answer.strip(),
                        "options": list(args.get("options", [])),
                    },
                    ensure_ascii=False,
                ),
                tool_call_id=ask_human_call.get("id", ""),
                name="tool_ask_human",
            )
        )
        return {
            "messages": tool_messages,
            "active_smiles": new_active_smiles,
            "artifacts": artifacts,
            "tasks": new_tasks,
        }

    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_call_id = tool_call.get("id", "")
        args = tool_call.get("args", {})
        tool = _TOOL_LOOKUP.get(tool_name)

        if tool is None:
            tool_messages.append(
                ToolMessage(
                    content=json.dumps({"error": f"Tool {tool_name} not found"}, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
            )
            continue

        try:
            raw_output = await tool.ainvoke(args, config=config)
            parsed = parse_tool_output(raw_output)

            if parsed is not None:
                if tool_name == "tool_update_task_status":
                    requested_task_id = str(parsed.get("task_id", "")).strip()
                    requested_status = str(parsed.get("task_status", "")).strip()

                    if requested_status in {"in_progress", "completed", "failed"}:
                        new_tasks, updated_task = update_tasks(new_tasks, requested_task_id, requested_status)
                        if updated_task is None:
                            parsed = {
                                "status": "error",
                                "error": f"Task {requested_task_id} not found in current plan",
                                "known_task_ids": [task["id"] for task in new_tasks],
                            }
                        else:
                            await dispatch_task_update(new_tasks, config, source="tools_executor")
                            parsed = {
                                "status": "success",
                                "task_id": updated_task["id"],
                                "task_status": updated_task["status"],
                                "description": updated_task["description"],
                            }
                    else:
                        parsed = {
                            "status": "error",
                            "error": f"Unsupported task status: {requested_status}",
                        }
                else:
                    new_active_smiles = apply_active_smiles_update(tool_name, parsed, new_active_smiles)
                    postprocessor = TOOL_POSTPROCESSORS.get(tool_name)
                    if postprocessor is not None:
                        parsed = await postprocessor(parsed, args, artifacts, config)

            content = tool_result_to_text(parsed) if parsed is not None else str(raw_output)
            tool_messages.append(
                ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
            )

        except Exception as exc:
            tool_messages.append(
                ToolMessage(
                    content=json.dumps({"error": str(exc)}, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
            )

    return {
        "messages": tool_messages,
        "active_smiles": new_active_smiles,
        "artifacts": artifacts,
        "tasks": new_tasks,
    }
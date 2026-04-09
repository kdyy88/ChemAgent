from __future__ import annotations

import json
import logging
import os
from typing import cast

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.agents.lg_tools import ALL_CHEM_TOOLS
from app.agents.postprocessors import TOOL_POSTPROCESSORS
from app.agents.state import ChemState, MoleculeWorkspaceEntry, Task, TaskStatus
from app.agents.utils import (
    apply_active_smiles_update,
    dispatch_task_update,
    format_molecule_workspace_for_prompt,
    merge_molecule_workspace,
    parse_tool_output,
    strip_binary_fields_with_report,
    tool_result_to_text,
    update_molecule_workspace,
    update_tasks,
)

_TOOL_LOOKUP = {tool.name: tool for tool in ALL_CHEM_TOOLS}
logger = logging.getLogger(__name__)
_MAX_PARENT_ARTIFACT_IDS = 8
_SUB_AGENT_VERBOSE_LOGS = os.environ.get("CHEMAGENT_SUB_AGENT_VERBOSE_LOGS", "").strip().lower() in {"1", "true", "yes", "on"}

# Tools that require explicit user approval before execution (Hard Breakpoint tier).
# Add tool names here to gate them behind the ApprovalCard UI.
HEAVY_TOOLS: frozenset[str] = frozenset()


def _merge_sub_agent_artifacts(existing: list[dict], produced: list[dict]) -> list[dict]:
    seen_ids = {
        str(artifact.get("artifact_id") or "").strip()
        for artifact in existing
        if isinstance(artifact, dict) and str(artifact.get("artifact_id") or "").strip()
    }
    merged: list[dict] = []

    for artifact in produced:
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("artifact_id") or "").strip()
        if artifact_id:
            if artifact_id in seen_ids:
                continue
            seen_ids.add(artifact_id)
        merged.append(artifact)

    return merged


def _collect_recent_artifact_ids(artifacts: list[dict], limit: int = _MAX_PARENT_ARTIFACT_IDS) -> list[str]:
    recent_ids: list[str] = []
    for artifact in reversed(artifacts):
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("artifact_id") or "").strip()
        if artifact_id and artifact_id not in recent_ids:
            recent_ids.append(artifact_id)
        if len(recent_ids) >= limit:
            break
    recent_ids.reverse()
    return recent_ids


def _sanitize_message_bus_payload(tool_name: str, parsed: dict | None) -> dict | None:
    if parsed is None:
        return None

    cleaned, removed_fields = strip_binary_fields_with_report(parsed)
    if removed_fields:
        removed_fields = sorted(removed_fields)
        logger.warning(
            "Stripped bulky payload fields from tool result before LLM exposure: tool=%s fields=%s",
            tool_name,
            removed_fields,
        )
        cleaned = dict(cleaned)
        cleaned.setdefault("artifact_payloads_removed", removed_fields)

    return cleaned


def _increments_evidence_revision(tool_name: str, parsed: dict | None) -> bool:
    if parsed is None:
        return False
    if tool_name == "tool_update_task_status":
        return False
    if tool_name == "tool_ask_human":
        return True

    status = str(parsed.get("status") or "").strip().lower()
    if status in {"error", "failed", "rejected"}:
        return False
    return True


async def tools_executor_node(state: ChemState, config: RunnableConfig) -> dict:
    last_message = state["messages"][-1]
    new_active_smiles = state.get("active_smiles")
    molecule_workspace: list[MoleculeWorkspaceEntry] = [
        cast(MoleculeWorkspaceEntry, dict(entry))
        for entry in state.get("molecule_workspace", [])
        if isinstance(entry, dict)
    ]
    new_tasks: list[Task] = [cast(Task, dict(task)) for task in state.get("tasks", [])]
    evidence_revision = int(state.get("evidence_revision") or 0)
    parent_artifacts = state.get("artifacts") or []
    recent_artifact_ids = _collect_recent_artifact_ids(parent_artifacts)
    active_artifact_id = recent_artifact_ids[-1] if recent_artifact_ids else None
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
                "evidence_revision": evidence_revision,
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
                "active_artifact_id": active_artifact_id,
                "recent_artifact_ids": recent_artifact_ids,
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
        evidence_revision += 1
        return {
            "messages": tool_messages,
            "active_smiles": new_active_smiles,
            "artifacts": artifacts,
            "tasks": new_tasks,
            "evidence_revision": evidence_revision,
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
            tool_config: RunnableConfig | dict = config
            if tool_name == "tool_run_sub_agent":
                requested_artifact_ids = [
                    str(artifact_id).strip()
                    for artifact_id in list(args.get("artifact_ids") or [])
                    if str(artifact_id).strip()
                ]
                if not requested_artifact_ids and recent_artifact_ids:
                    logger.warning(
                        "Sub-agent dispatch omitted artifact_ids despite available parent artifacts: active_artifact_id=%s parent_artifact_ids=%s",
                        active_artifact_id or "",
                        recent_artifact_ids,
                    )
                if _SUB_AGENT_VERBOSE_LOGS:
                    logger.debug(
                        "Sub-agent dispatch payload: requested_artifact_ids=%s active_artifact_id=%s parent_artifact_ids=%s active_smiles_present=%s context_chars=%d task=%.160s",
                        requested_artifact_ids,
                        active_artifact_id or "",
                        recent_artifact_ids,
                        bool(new_active_smiles),
                        len(str(args.get("context") or "")),
                        str(args.get("task") or ""),
                    )
                configurable = dict((config or {}).get("configurable") or {})
                configurable["parent_active_smiles"] = new_active_smiles or ""
                configurable["parent_active_artifact_id"] = active_artifact_id or ""
                configurable["parent_artifact_ids"] = recent_artifact_ids
                configurable["parent_molecule_workspace_summary"] = format_molecule_workspace_for_prompt(
                    molecule_workspace,
                    new_active_smiles,
                )
                tool_config = dict(config or {})
                tool_config["configurable"] = configurable

            raw_output = await tool.ainvoke(args, config=tool_config)
            parsed = parse_tool_output(raw_output)

            if parsed is not None:
                if tool_name == "tool_update_task_status":
                    requested_task_id = str(parsed.get("task_id", "")).strip()
                    requested_status = str(parsed.get("task_status", "")).strip()
                    requested_summary = str(parsed.get("summary") or "").strip()

                    if requested_status in {"in_progress", "completed", "failed"}:
                        new_tasks, updated_task, ignored_reason = update_tasks(
                            new_tasks,
                            requested_task_id,
                            cast(TaskStatus, requested_status),
                            evidence_revision,
                            requested_summary,
                        )
                        if updated_task is None:
                            parsed = {
                                "status": "error",
                                "error": f"Task {requested_task_id} not found in current plan",
                                "known_task_ids": [task["id"] for task in new_tasks],
                            }
                        elif ignored_reason is not None:
                            parsed = {
                                "status": "ignored",
                                "task_id": updated_task["id"],
                                "task_status": updated_task["status"],
                                "description": updated_task["description"],
                                "summary": updated_task.get("summary", ""),
                                "reason": ignored_reason,
                            }
                        else:
                            await dispatch_task_update(new_tasks, config, source="tools_executor")
                            parsed = {
                                "status": "success",
                                "task_id": updated_task["id"],
                                "task_status": updated_task["status"],
                                "description": updated_task["description"],
                                "summary": updated_task.get("summary", ""),
                            }
                    else:
                        parsed = {
                            "status": "error",
                            "error": f"Unsupported task status: {requested_status}",
                        }
                elif tool_name == "tool_run_sub_agent":
                    produced_artifacts = parsed.get("produced_artifacts")
                    if isinstance(produced_artifacts, list):
                        artifacts.extend(_merge_sub_agent_artifacts(parent_artifacts, produced_artifacts))

                    suggested_active_smiles = str(parsed.get("suggested_active_smiles") or "").strip()
                    if suggested_active_smiles:
                        new_active_smiles = suggested_active_smiles

                    molecule_workspace = merge_molecule_workspace(
                        molecule_workspace,
                        parsed.get("molecule_workspace") if isinstance(parsed.get("molecule_workspace"), list) else [],
                    )

                    if _SUB_AGENT_VERBOSE_LOGS:
                        logger.debug(
                            "Sub-agent return payload: status=%s sub_thread_id=%s produced_artifacts=%d merged_artifacts=%d suggested_active_smiles_present=%s result_chars=%d",
                            parsed.get("status", "ok"),
                            parsed.get("sub_thread_id"),
                            len(produced_artifacts) if isinstance(produced_artifacts, list) else 0,
                            len(artifacts),
                            bool(suggested_active_smiles),
                            len(str(parsed.get("result") or parsed.get("response") or "")),
                        )

                    parsed = {
                        "status": parsed.get("status", "ok"),
                        "mode": parsed.get("mode"),
                        "sub_thread_id": parsed.get("sub_thread_id"),
                        "task_kind": parsed.get("task_kind"),
                        "output_contract": parsed.get("output_contract"),
                        "smiles_policy": parsed.get("smiles_policy"),
                        "result": parsed.get("result") or parsed.get("response") or "",
                        "response": parsed.get("result") or parsed.get("response") or "",
                        "findings": parsed.get("findings") if isinstance(parsed.get("findings"), list) else [],
                        "candidate_cores": parsed.get("candidate_cores") if isinstance(parsed.get("candidate_cores"), list) else [],
                        "candidate_smiles": parsed.get("candidate_smiles") if isinstance(parsed.get("candidate_smiles"), list) else [],
                        "policy_conflicts": parsed.get("policy_conflicts") if isinstance(parsed.get("policy_conflicts"), list) else [],
                        "needs_followup": bool(parsed.get("needs_followup")),
                        "recommended_mode": parsed.get("recommended_mode"),
                        "recommended_task_kind": parsed.get("recommended_task_kind"),
                        "molecule_workspace": molecule_workspace,
                    }
                else:
                    new_active_smiles = apply_active_smiles_update(tool_name, parsed, new_active_smiles)
                    molecule_workspace = update_molecule_workspace(molecule_workspace, tool_name, parsed, args)
                    postprocessor = TOOL_POSTPROCESSORS.get(tool_name)
                    if postprocessor is not None:
                        parsed = await postprocessor(parsed, args, artifacts, config)

                parsed = _sanitize_message_bus_payload(tool_name, parsed)

            if _increments_evidence_revision(tool_name, parsed):
                evidence_revision += 1

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
        "molecule_workspace": molecule_workspace,
        "tasks": new_tasks,
        "evidence_revision": evidence_revision,
    }
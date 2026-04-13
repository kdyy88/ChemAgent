from __future__ import annotations

import hashlib
import json
import logging
import os
from uuid import uuid4
from typing import Any, cast

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.agents.contracts.protocol import RecoveryAction, NodeUpdate, NodeCreate  # noqa: F401 (NodeUpdate/NodeCreate used for type hint comments only)
from app.agents.postprocessors import TOOL_POSTPROCESSORS
from app.domain.schemas.agent import ChemState, MoleculeWorkspaceEntry, Task, TaskStatus
from app.tools.registry import get_root_tools
from app.agents.utils import (
    apply_active_smiles_update,
    dispatch_task_update,
    format_molecule_workspace_for_prompt,
    merge_molecule_workspace,
    parse_tool_output,
    sanitize_messages_for_state,
    strip_binary_fields_with_report,
    tool_result_to_text,
    update_molecule_workspace,
    update_tasks,
)
from app.domain.store.plan_store import read_plan_file
from app.domain.store.artifact_store import get_engine_artifact, get_engine_artifact_warning

_TOOL_LOOKUP = {tool.name: tool for tool in get_root_tools()}
logger = logging.getLogger(__name__)
_MAX_PARENT_ARTIFACT_IDS = 8
_SUB_AGENT_VERBOSE_LOGS = os.environ.get("CHEMAGENT_SUB_AGENT_VERBOSE_LOGS", "").strip().lower() in {"1", "true", "yes", "on"}

# ---------------------------------------------------------------------------
# Auto-harvest: tools in this set trigger automatic molecule_tree population
# when they succeed (is_valid=true) and carry a 'smiles' argument.  This lets
# Phase 3 viewport/molecule_tree stay populated without requiring every tool
# implementation to explicitly return NodeCreate/NodeUpdate.
# ---------------------------------------------------------------------------
_HARVEST_TOOLS = frozenset({
    "tool_render_smiles",
    "tool_build_3d_conformer",
    "tool_evaluate_molecule",
    "tool_compute_mol_properties",
})


def _smiles_to_artifact_id(canonical_smiles: str) -> str:
    """Stable artifact ID from canonical SMILES (matches engine.py convention)."""
    return "mol_" + hashlib.md5(canonical_smiles.encode()).hexdigest()[:8]


def _auto_harvest_molecule_node(
    tool_name: str,
    args: dict,
    parsed: Any,
    current_tree: dict,
    molecule_tree_updates: dict,
    node_create_ids: list,
) -> None:
    """Inspect a legacy-path tool result and auto-register a MoleculeNode when
    a valid SMILES was processed.  No-ops silently if conditions aren't met."""
    if tool_name not in _HARVEST_TOOLS:
        return
    if not isinstance(parsed, dict):
        return
    if not parsed.get("is_valid"):
        return

    # Prefer canonical SMILES from result; fall back to raw input arg.
    smiles = str(parsed.get("canonical_smiles") or parsed.get("smiles") or args.get("smiles") or "").strip()
    if not smiles:
        return

    artifact_id = _smiles_to_artifact_id(smiles)
    # Don't overwrite nodes that already have a richer status set by the LLM.
    if artifact_id in molecule_tree_updates:
        return

    # Build the node, preserving any existing tree entry for this molecule.
    existing = dict(current_tree.get(artifact_id) or {})
    compound_name: str = str(
        args.get("compound_name") or args.get("name") or parsed.get("compound_name") or ""
    ).strip()
    aliases: list[str] = list(existing.get("aliases") or [])
    if compound_name and compound_name not in aliases:
        aliases.append(compound_name)

    molecule_tree_updates[artifact_id] = {
        **existing,
        "artifact_id": artifact_id,
        "smiles": smiles,
        "status": existing.get("status") or "staged",
        "aliases": aliases,
        "diagnostics": existing.get("diagnostics") or {},
    }
    if artifact_id not in node_create_ids and artifact_id not in current_tree:
        node_create_ids.append(artifact_id)
_MAX_SUBTASK_RECOVERY_ATTEMPTS = 1

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


def _unique_nonempty_strings(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _prepare_sub_agent_artifact_inputs(
    args: dict[str, Any],
    *,
    active_artifact_id: str | None,
    parent_artifact_ids: list[str],
) -> tuple[dict[str, Any], list[str]]:
    prepared_args = dict(args)
    delegation_raw = prepared_args.get("delegation")
    delegation: dict[str, Any] = dict(delegation_raw) if isinstance(delegation_raw, dict) else {}

    explicit_artifact_ids = _unique_nonempty_strings(
        [str(artifact_id) for artifact_id in list(prepared_args.get("artifact_ids") or [])]
    )
    delegated_artifact_ids = _unique_nonempty_strings(
        [str(artifact_id) for artifact_id in list(delegation.get("artifact_pointers") or [])]
    )
    inherited_artifact_ids = _unique_nonempty_strings([
        *parent_artifact_ids,
        str(active_artifact_id or ""),
    ])

    requested_artifact_ids = explicit_artifact_ids or delegated_artifact_ids or inherited_artifact_ids
    if requested_artifact_ids:
        prepared_args["artifact_ids"] = requested_artifact_ids
        delegation["artifact_pointers"] = requested_artifact_ids
        if not str(delegation.get("active_artifact_id") or "").strip() and active_artifact_id:
            delegation["active_artifact_id"] = str(active_artifact_id).strip()
        prepared_args["delegation"] = delegation

    return prepared_args, requested_artifact_ids


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


def _normalize_subagent_delegation(args: dict) -> dict:
    raw_delegation = args.get("delegation")
    if isinstance(raw_delegation, dict):
        return dict(raw_delegation)
    return {}


def _build_recovery_hint(failure: dict, *, for_spawn: bool) -> str:
    summary = str(failure.get("summary") or "").strip()
    error = str(failure.get("error") or "").strip()
    tool_name = str(failure.get("failed_tool_name") or "").strip()
    prefix = "Spawn new worker" if for_spawn else "Continue same worker"
    parts = [prefix, "avoid repeating the previous failing path"]
    if tool_name:
        parts.append(f"failing_tool={tool_name}")
    if summary:
        parts.append(f"summary={summary}")
    if error:
        parts.append(f"error={error}")
    return " | ".join(parts)


def _prepare_recovery_dispatch(
    *,
    args: dict,
    tool_config: RunnableConfig | dict,
    parsed: dict,
) -> tuple[dict, dict, str] | None:
    failure = parsed.get("failure") if isinstance(parsed.get("failure"), dict) else None
    if failure is None:
        return None

    configurable = dict((tool_config or {}).get("configurable") or {})
    recovery_attempts = int(configurable.get("subtask_recovery_attempts") or 0)
    if recovery_attempts >= _MAX_SUBTASK_RECOVERY_ATTEMPTS:
        return None

    recommended_action = str(failure.get("recommended_action") or RecoveryAction.spawn_new_task.value).strip().lower()
    is_recoverable = bool(failure.get("is_recoverable"))

    should_continue = recommended_action == RecoveryAction.continue_same_task.value and is_recoverable
    should_spawn = recommended_action == RecoveryAction.spawn_new_task.value or not is_recoverable
    if not should_continue and not should_spawn:
        return None

    recovery_args = dict(args)
    recovery_config = dict(tool_config or {})
    recovery_configurable = dict(configurable)
    recovery_configurable["subtask_recovery_attempts"] = recovery_attempts + 1
    delegation = _normalize_subagent_delegation(recovery_args)
    existing_inline_context = str(delegation.get("inline_context") or "").strip()

    if should_continue:
        recovery_hint = _build_recovery_hint(failure, for_spawn=False)
        merged_inline_context = recovery_hint if not existing_inline_context else f"{existing_inline_context}\n\n{recovery_hint}"
        delegation["inline_context"] = merged_inline_context[:1400]
        if parsed.get("execution_task_id"):
            recovery_configurable["execution_task_id"] = str(parsed.get("execution_task_id"))
        recovery_args["delegation"] = delegation
        recovery_config["configurable"] = recovery_configurable
        return recovery_args, recovery_config, RecoveryAction.continue_same_task.value

    recovery_hint = _build_recovery_hint(failure, for_spawn=True)
    delegation["inline_context"] = recovery_hint[:1400]
    recovery_args["delegation"] = delegation
    recovery_configurable["execution_task_id"] = uuid4().hex
    recovery_config["configurable"] = recovery_configurable
    return recovery_args, recovery_config, RecoveryAction.spawn_new_task.value


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
    active_subtasks = {
        str(task_id): dict(pointer)
        for task_id, pointer in (state.get("active_subtasks") or {}).items()
        if isinstance(pointer, dict)
    }
    active_subtask_id = str(state.get("active_subtask_id") or "").strip() or None
    parent_artifacts = state.get("artifacts") or []
    recent_artifact_ids = _collect_recent_artifact_ids(parent_artifacts)
    active_artifact_id = recent_artifact_ids[-1] if recent_artifact_ids else None
    artifacts: list[dict] = []
    tool_messages: list[ToolMessage] = []
    tool_calls = list(getattr(last_message, "tool_calls", []))

    # Protocol accumulators for Chem LSP (Phase 3)
    current_tree: dict[str, Any] = dict(state.get("molecule_tree") or {})
    molecule_tree_updates: dict[str, Any] = {}
    node_create_ids: list[str] = []

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
            "messages": await sanitize_messages_for_state(tool_messages, source="tools_executor.clarification"),
            "active_smiles": new_active_smiles,
            "artifacts": artifacts,
            "tasks": new_tasks,
            "evidence_revision": evidence_revision,
        }

    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_call_id = tool_call.get("id", "")
        args: dict[str, Any] = dict(tool_call.get("args", {}) if isinstance(tool_call.get("args"), dict) else {})
        if isinstance(args, dict) and args.get("__redacted__") and args.get("__artifact_id__"):
            restored_args = await get_engine_artifact(str(args.get("__artifact_id__")))
            if isinstance(restored_args, dict):
                args = dict(restored_args)
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
            logger.info("\ud83d\udd27 [ToolDispatch] tool=%s  args_keys=%s", tool_name, list(args.keys()))
            if tool_name == "tool_run_sub_agent":
                args, requested_artifact_ids = _prepare_sub_agent_artifact_inputs(
                    args,
                    active_artifact_id=active_artifact_id,
                    parent_artifact_ids=recent_artifact_ids,
                )
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

            if isinstance(parsed, dict):
                _status = parsed.get("status", "ok")
                _err = parsed.get("error")
                if _err:
                    logger.info("\u274c [ToolResult] tool=%s  status=%s  error=%.120s", tool_name, _status, _err)
                elif tool_name != "tool_update_task_status":
                    logger.info("\u2705 [ToolResult] tool=%s  status=%s  keys=%s", tool_name, _status, list(parsed.keys()))

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
                    subagent_payload: dict[str, Any] = parsed
                    produced_artifacts = subagent_payload.get("produced_artifacts")
                    if isinstance(produced_artifacts, list):
                        artifacts.extend(_merge_sub_agent_artifacts(parent_artifacts, produced_artifacts))

                    if str(subagent_payload.get("status") or "").strip().lower() == "plan_pending_approval":
                        plan_pointer_raw = subagent_payload.get("plan_pointer")
                        plan_pointer: dict[str, Any] = dict(plan_pointer_raw) if isinstance(plan_pointer_raw, dict) else {}
                        plan_id = str(plan_pointer.get("plan_id") or "").strip()
                        if plan_id:
                            active_subtasks[plan_id] = {
                                "kind": "plan",
                                "status": "pending_approval",
                                "summary": str(subagent_payload.get("summary") or "").strip(),
                                "plan_id": plan_id,
                                "plan_file_ref": str(plan_pointer.get("plan_file_ref") or "").strip(),
                            }
                            active_subtask_id = plan_id

                        resume_value = interrupt(
                            {
                                "type": "plan_approval_request",
                                "plan_id": plan_id,
                                "plan_file_ref": str(plan_pointer.get("plan_file_ref") or "").strip(),
                                "summary": str(subagent_payload.get("summary") or "").strip(),
                                "status": "pending_approval",
                                "mode": str(subagent_payload.get("mode") or "plan"),
                            }
                        )

                        action = str((resume_value or {}).get("action") or "").strip().lower() if isinstance(resume_value, dict) else ""
                        if action == "reject_plan":
                            if plan_id:
                                active_subtasks.pop(plan_id, None)
                                if active_subtask_id == plan_id:
                                    active_subtask_id = None
                            parsed = {
                                "status": "rejected",
                                "mode": subagent_payload.get("mode"),
                                "summary": "计划已被人工拒绝，等待重新规划。",
                                "result": "计划已被人工拒绝，等待重新规划。",
                                "response": "计划已被人工拒绝，等待重新规划。",
                                "plan_pointer": plan_pointer,
                                "needs_followup": True,
                            }
                        else:
                            approved_plan_id = str((resume_value or {}).get("plan_id") or plan_id).strip()
                            _, approved_plan_markdown = read_plan_file(
                                session_id=str(((config or {}).get("configurable") or {}).get("thread_id") or "default"),
                                plan_id=approved_plan_id,
                            )
                            execution_task_id = uuid4().hex
                            execution_args = dict(args)
                            execution_args["mode"] = "general"
                            execution_args["task"] = f"执行已批准计划：{str(args.get('task') or '').strip()}"[:1000]

                            execution_delegation = dict(execution_args.get("delegation") or {})
                            existing_inline_context = str(execution_delegation.get("inline_context") or "").strip()
                            approved_plan_context = f"Approved plan ({approved_plan_id}):\n{approved_plan_markdown}".strip()
                            merged_inline_context = approved_plan_context if not existing_inline_context else f"{existing_inline_context}\n\n{approved_plan_context}"
                            execution_delegation["inline_context"] = merged_inline_context[:1400]
                            execution_delegation["subagent_type"] = "general"
                            execution_delegation["task_directive"] = execution_args["task"]
                            execution_args["delegation"] = execution_delegation

                            execution_config = dict(tool_config or {})
                            execution_configurable_raw = execution_config.get("configurable")
                            execution_configurable: dict[str, Any] = (
                                dict(execution_configurable_raw)
                                if isinstance(execution_configurable_raw, dict)
                                else {}
                            )
                            execution_configurable["execution_task_id"] = execution_task_id
                            execution_configurable.pop("plan_id", None)
                            execution_config["configurable"] = execution_configurable

                            active_subtasks[execution_task_id] = {
                                "kind": "execution",
                                "status": "running",
                                "summary": str(subagent_payload.get("summary") or "").strip(),
                                "plan_id": approved_plan_id,
                                "plan_file_ref": str(plan_pointer.get("plan_file_ref") or "").strip(),
                                "execution_task_id": execution_task_id,
                            }
                            active_subtask_id = execution_task_id
                            active_subtasks.pop(approved_plan_id, None)

                            raw_output = await tool.ainvoke(execution_args, config=execution_config)
                            parsed = parse_tool_output(raw_output)
                            if str((parsed or {}).get("status") or "").strip().lower() in {"ok", "failed", "stopped", "error", "timeout", "protocol_error"}:
                                active_subtasks.pop(execution_task_id, None)
                                if active_subtask_id == execution_task_id:
                                    active_subtask_id = None

                    recovery_dispatch = None
                    parsed_dict: dict[str, Any] | None = parsed if isinstance(parsed, dict) else None
                    if parsed_dict is not None and str(parsed_dict.get("status") or "").strip().lower() == "failed":
                        recovery_dispatch = _prepare_recovery_dispatch(
                            args=args,
                            tool_config=tool_config,
                            parsed=parsed_dict,
                        )

                    if recovery_dispatch is not None:
                        recovery_args, recovery_config, recovery_action = recovery_dispatch
                        prior_execution_task_id = str(parsed_dict.get("execution_task_id") or "").strip() if parsed_dict is not None else ""
                        if recovery_action == RecoveryAction.spawn_new_task.value and prior_execution_task_id:
                            active_subtasks.pop(prior_execution_task_id, None)
                            if active_subtask_id == prior_execution_task_id:
                                active_subtask_id = None

                        raw_output = await tool.ainvoke(recovery_args, config=recovery_config)
                        parsed = parse_tool_output(raw_output)
                        if isinstance(parsed, dict):
                            parsed["parent_decision"] = recovery_action

                        parsed_dict: dict[str, Any] | None = parsed if isinstance(parsed, dict) else None
                        recovered_execution_task_id = str(parsed_dict.get("execution_task_id") or "").strip() if parsed_dict is not None else ""
                        if recovered_execution_task_id and recovery_action == RecoveryAction.spawn_new_task.value:
                            active_subtasks[recovered_execution_task_id] = {
                                "kind": "execution",
                                "status": str(parsed_dict.get("status") or "running") if parsed_dict is not None else "running",
                                "summary": str(parsed_dict.get("summary") or "").strip() if parsed_dict is not None else "",
                                "execution_task_id": recovered_execution_task_id,
                            }
                            active_subtask_id = recovered_execution_task_id
                        if parsed_dict is not None and str(parsed_dict.get("status") or "").strip().lower() in {"ok", "failed", "stopped", "error", "timeout", "protocol_error"} and recovered_execution_task_id:
                            active_subtasks.pop(recovered_execution_task_id, None)
                            if active_subtask_id == recovered_execution_task_id:
                                active_subtask_id = None

                    parsed_dict = parsed if isinstance(parsed, dict) else {}
                    completion_raw = parsed_dict.get("completion")
                    completion: dict[str, Any] = dict(completion_raw) if isinstance(completion_raw, dict) else {}
                    suggested_active_smiles = str(
                        parsed_dict.get("suggested_active_smiles")
                        or parsed_dict.get("advisory_active_smiles")
                        or completion.get("advisory_active_smiles")
                        or ""
                    ).strip()
                    if suggested_active_smiles:
                        new_active_smiles = suggested_active_smiles

                    if _SUB_AGENT_VERBOSE_LOGS:
                        logger.debug(
                            "Sub-agent return payload: status=%s sub_thread_id=%s produced_artifacts=%d merged_artifacts=%d suggested_active_smiles_present=%s summary_chars=%d report_ref=%s",
                            parsed_dict.get("status", "ok"),
                            parsed_dict.get("sub_thread_id"),
                            len(produced_artifacts) if isinstance(produced_artifacts, list) else 0,
                            len(artifacts),
                            bool(suggested_active_smiles),
                            len(str(parsed_dict.get("summary") or parsed_dict.get("result") or parsed_dict.get("response") or "")),
                            (parsed_dict.get("scratchpad_report_ref") or {}).get("scratchpad_id") if isinstance(parsed_dict.get("scratchpad_report_ref"), dict) else None,
                        )

                    parsed = {
                        "status": parsed_dict.get("status", "ok"),
                        "mode": parsed_dict.get("mode"),
                        "sub_thread_id": parsed_dict.get("sub_thread_id"),
                        "execution_task_id": parsed_dict.get("execution_task_id"),
                        "task_kind": parsed_dict.get("task_kind"),
                        "output_contract": parsed_dict.get("output_contract"),
                        "smiles_policy": parsed_dict.get("smiles_policy"),
                        "summary": parsed_dict.get("summary") or parsed_dict.get("result") or parsed_dict.get("response") or "",
                        "result": parsed_dict.get("summary") or parsed_dict.get("result") or parsed_dict.get("response") or "",
                        "response": parsed_dict.get("summary") or parsed_dict.get("result") or parsed_dict.get("response") or "",
                        "completion": completion,
                        "plan_pointer": parsed_dict.get("plan_pointer") if isinstance(parsed_dict.get("plan_pointer"), dict) else None,
                        "failure": parsed_dict.get("failure") if isinstance(parsed_dict.get("failure"), dict) else None,
                        "delegation": parsed_dict.get("delegation") if isinstance(parsed_dict.get("delegation"), dict) else None,
                        "scratchpad_report_ref": parsed_dict.get("scratchpad_report_ref") if isinstance(parsed_dict.get("scratchpad_report_ref"), dict) else None,
                        "policy_conflicts": parsed_dict.get("policy_conflicts") if isinstance(parsed_dict.get("policy_conflicts"), list) else [],
                        "needs_followup": bool(parsed_dict.get("needs_followup")),
                        "parent_decision": parsed_dict.get("parent_decision"),
                        "recommended_mode": parsed_dict.get("recommended_mode"),
                        "recommended_task_kind": parsed_dict.get("recommended_task_kind"),
                        "suggested_active_smiles": suggested_active_smiles or None,
                        "produced_artifacts": produced_artifacts if isinstance(produced_artifacts, list) else [],
                    }

                    failure = parsed.get("failure") if isinstance(parsed.get("failure"), dict) else None
                    if failure is not None:
                        recommended_action = str(failure.get("recommended_action") or RecoveryAction.spawn_new_task.value)
                        parsed["parent_decision"] = recommended_action
                else:
                    # ── Chem LSP protocol branch ───────────────────────────
                    protocol_type = (parsed or {}).get("__chem_protocol__")
                    if protocol_type == "NodeUpdate":
                        aid = str(parsed["artifact_id"])
                        existing = dict(current_tree.get(aid) or {"artifact_id": aid, "smiles": "", "status": "staged"})
                        molecule_tree_updates[aid] = {
                            **existing,
                            "diagnostics": {**(existing.get("diagnostics") or {}), **dict(parsed.get("diagnostics") or {})},
                            **(({"status": parsed["status"]}) if parsed.get("status") else {}),
                        }
                    elif protocol_type == "NodeCreate":
                        aid = str(parsed["artifact_id"])
                        molecule_tree_updates[aid] = {
                            "artifact_id": aid,
                            "smiles": str(parsed.get("smiles") or ""),
                            "parent_id": parsed.get("parent_id"),
                            "status": str(parsed.get("status") or "staged"),
                            "diagnostics": dict(parsed.get("diagnostics") or {}),
                        }
                        if aid not in node_create_ids:
                            node_create_ids.append(aid)
                    else:
                        # ── Legacy path — unchanged ───────────────────────
                        new_active_smiles = apply_active_smiles_update(tool_name, parsed, new_active_smiles)
                        molecule_workspace = update_molecule_workspace(molecule_workspace, tool_name, parsed, args)
                        postprocessor = TOOL_POSTPROCESSORS.get(tool_name)
                        if postprocessor is not None:
                            parsed = await postprocessor(parsed, args, artifacts, config)
                        # Auto-harvest: register a MoleculeNode for tools that
                        # consume a SMILES and return a validated structure.
                        _auto_harvest_molecule_node(
                            tool_name, args, parsed,
                            current_tree, molecule_tree_updates, node_create_ids,
                        )

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
            logger.warning("\ud83d\udca5 [ToolError] tool=%s  error=%s", tool_name, exc)
            tool_messages.append(
                ToolMessage(
                    content=json.dumps({"error": str(exc)}, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
            )

    # Refresh the artifact expiry warning so the next agent turn can read it
    # from state without reaching into the storage layer.
    all_artifacts = (state.get("artifacts") or []) + artifacts
    active_artifact_id = all_artifacts[-1].get("artifact_id") if all_artifacts else None
    artifact_expiry_warning = await get_engine_artifact_warning(
        str(active_artifact_id or "").strip()
    )

    return {
        "messages": await sanitize_messages_for_state(tool_messages, source="tools_executor"),
        "active_smiles": new_active_smiles,
        "artifacts": artifacts,
        "molecule_workspace": molecule_workspace,
        "tasks": new_tasks,
        "evidence_revision": evidence_revision,
        "active_subtasks": active_subtasks,
        "active_subtask_id": active_subtask_id,
        "artifact_expiry_warning": artifact_expiry_warning,
        # Chem LSP protocol writes — only emitted when non-empty so unrelated
        # turns don't trigger unnecessary LangGraph reducer calls.
        **(({"molecule_tree": molecule_tree_updates}) if molecule_tree_updates else {}),
        **(
            {
                "viewport": {
                    **({"focused_artifact_ids": [], **dict(state.get("viewport") or {})}),
                    "focused_artifact_ids": list(
                        dict.fromkeys(
                            list((state.get("viewport") or {}).get("focused_artifact_ids") or [])
                            + node_create_ids
                        )
                    ),
                }
            }
            if node_create_ids
            else {}
        ),
    }
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agents.subagent_protocol import (
    ExitPlanModePayload,
    FailureCategory,
    PlanPointer,
    RecoveryAction,
    ReportFailurePayload,
    ScratchpadKind,
    TaskStopPayload,
)
from app.core.scratchpad_store import create_scratchpad_entry, read_scratchpad_entry
from app.core.plan_store import read_plan_file, write_plan_file

logger = logging.getLogger(__name__)


def _runtime_ids() -> tuple[str, str]:
    from langgraph.config import get_config as _lg_get_config  # noqa: PLC0415

    config = _lg_get_config()
    configurable = config.get("configurable") or {}
    session_id = str(configurable.get("scratchpad_session_id") or configurable.get("parent_thread_id") or configurable.get("thread_id") or "default").strip()
    sub_thread_id = str(configurable.get("thread_id") or "default").strip()
    return session_id, sub_thread_id


def _runtime_configurable() -> dict[str, Any]:
    from langgraph.config import get_config as _lg_get_config  # noqa: PLC0415

    config = _lg_get_config()
    return config.get("configurable") or {}


def _runtime_plan_id() -> str:
    configurable = _runtime_configurable()
    existing = str(configurable.get("plan_id") or "").strip()
    if existing:
        return existing
    return str(uuid.uuid4())


class ReadScratchpadArgs(BaseModel):
    scratchpad_id: str = Field(description="Opaque scratchpad id to read.")


class WriteScratchpadArgs(BaseModel):
    content: str = Field(min_length=1, description="Plain-text content to persist into scratchpad.")
    kind: str = Field(default=ScratchpadKind.note.value, description="Scratchpad kind: note / report / context.")
    summary: str = Field(default="", description="Short summary for later recall.")
    extension: str = Field(default="md", description="Preferred extension for the stored payload.")


class TaskCompleteArgs(BaseModel):
    summary: str = Field(default="", description="Compact completion summary for the parent graph.")
    produced_artifact_ids: list[str] = Field(default_factory=list, description="Artifact ids created or selected during execution.")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Structured completion metrics.")
    advisory_active_smiles: str = Field(default="", description="Optional advisory active SMILES for the parent graph.")


class WritePlanArgs(BaseModel):
    content: str = Field(min_length=1, description="Markdown plan content to persist as the approval artifact.")
    summary: str = Field(default="", description="Optional short plan summary for the parent graph.")


class ExitPlanModeArgs(BaseModel):
    summary: str = Field(default="", description="Compact planning summary for the parent graph.")


class TaskStopArgs(BaseModel):
    summary: str = Field(default="", description="Compact stop summary for the parent graph.")
    reason: str = Field(default="", description="Human-readable reason for stopping.")
    is_recoverable: bool = Field(default=False, description="Whether the task can theoretically be resumed or repaired.")
    recommended_action: str = Field(default=RecoveryAction.abort.value, description="Recommended parent action: continue / spawn / abort.")


class ReportFailureArgs(BaseModel):
    summary: str = Field(default="", description="Compact failure summary for the parent graph.")
    error: str = Field(default="", description="Detailed failure or exception text.")
    failure_category: str = Field(default=FailureCategory.unknown.value, description="Failure category: infrastructure / validation / schema / policy / unsupported_tool / timeout / unknown.")
    failed_tool_name: str = Field(default="", description="Tool name involved in the failure, when applicable.")
    failed_args_signature: str = Field(default="", description="Normalized signature of the failing tool args.")
    is_recoverable: bool = Field(default=False, description="Whether the task can theoretically be resumed or repaired.")
    recommended_action: str = Field(default=RecoveryAction.spawn_new_task.value, description="Recommended parent action: continue / spawn / abort.")


@tool(args_schema=ReadScratchpadArgs)
def tool_read_scratchpad(scratchpad_id: str) -> str:
    """Read a scratchpad payload by opaque id from the current sub-agent sandbox."""
    session_id, sub_thread_id = _runtime_ids()
    logger.debug(
        "[SCRATCHPAD READ] id=%s session=%s thread=%s",
        scratchpad_id,
        session_id,
        sub_thread_id,
    )
    ref, content = read_scratchpad_entry(
        session_id=session_id,
        sub_thread_id=sub_thread_id,
        scratchpad_id=scratchpad_id,
    )
    return json.dumps(
        {
            "scratchpad_ref": ref.model_dump(mode="json"),
            "content": content,
        },
        ensure_ascii=False,
    )


@tool(args_schema=WriteScratchpadArgs)
def tool_write_scratchpad(
    content: str,
    kind: str = ScratchpadKind.note.value,
    summary: str = "",
    extension: str = "md",
) -> str:
    """Persist long-form text into the current sub-agent scratchpad sandbox."""
    session_id, sub_thread_id = _runtime_ids()
    ref = create_scratchpad_entry(
        session_id=session_id,
        sub_thread_id=sub_thread_id,
        kind=ScratchpadKind(kind),
        content=content,
        summary=summary,
        created_by="sub_agent",
        extension=extension,
    )
    logger.debug(
        "[SCRATCHPAD WRITE] id=%s kind=%s size_bytes=%d session=%s thread=%s summary=%r",
        ref.scratchpad_id,
        ref.kind.value,
        ref.size_bytes,
        session_id,
        sub_thread_id,
        (summary or "")[:80],
    )
    return json.dumps({"scratchpad_ref": ref.model_dump(mode="json")}, ensure_ascii=False)


@tool(args_schema=TaskCompleteArgs)
def tool_task_complete(
    summary: str = "",
    produced_artifact_ids: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
    advisory_active_smiles: str = "",
) -> str:
    """Finalize the sub-agent run with a structured payload for the parent graph."""
    artifact_ids = [
        str(artifact_id).strip()
        for artifact_id in (produced_artifact_ids or [])
        if str(artifact_id).strip()
    ]
    logger.info(
        "[TASK COMPLETE] summary=%r artifacts=%s smiles=%r metrics_keys=%s",
        (summary or "")[:120],
        artifact_ids,
        (advisory_active_smiles or "")[:60],
        list((metrics or {}).keys()),
    )
    return json.dumps(
        {
            "status": "completed",
            "summary": summary,
            "produced_artifact_ids": artifact_ids,
            "metrics": metrics or {},
            "advisory_active_smiles": advisory_active_smiles.strip(),
        },
        ensure_ascii=False,
    )


@tool(args_schema=WritePlanArgs)
def tool_write_plan(content: str, summary: str = "") -> str:
    """Persist a Markdown plan artifact for approval-driven execution."""
    session_id, _ = _runtime_ids()
    plan_id = _runtime_plan_id()
    pointer = write_plan_file(session_id=session_id, plan_id=plan_id, content=content)
    if summary.strip():
        pointer = PlanPointer.model_validate(
            {
                **pointer.model_dump(mode="json"),
                "summary": summary.strip(),
            }
        )
    return json.dumps(
        {
            "status": "plan_written",
            "plan": pointer.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )


@tool(args_schema=ExitPlanModeArgs)
def tool_exit_plan_mode(summary: str = "") -> str:
    """Terminate planning and surface a stable plan pointer for HITL approval."""
    session_id, _ = _runtime_ids()
    plan_id = _runtime_plan_id()
    pointer, content = read_plan_file(session_id=session_id, plan_id=plan_id)
    pointer = PlanPointer.model_validate(
        {
            **pointer.model_dump(mode="json"),
            "status": "pending_approval",
            "summary": summary.strip() or pointer.summary,
        }
    )
    payload = ExitPlanModePayload(
        plan=pointer,
        summary=summary.strip() or pointer.summary or content[:160],
    )
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=TaskStopArgs)
def tool_task_stop(
    summary: str = "",
    reason: str = "",
    is_recoverable: bool = False,
    recommended_action: str = RecoveryAction.abort.value,
) -> str:
    """Stop the child task intentionally and return a structured payload."""
    payload = TaskStopPayload(
        summary=summary,
        reason=reason,
        is_recoverable=is_recoverable,
        recommended_action=RecoveryAction(recommended_action),
    )
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=ReportFailureArgs)
def tool_report_failure(
    summary: str = "",
    error: str = "",
    failure_category: str = FailureCategory.unknown.value,
    failed_tool_name: str = "",
    failed_args_signature: str = "",
    is_recoverable: bool = False,
    recommended_action: str = RecoveryAction.spawn_new_task.value,
) -> str:
    """Return a structured stop-loss payload when the child cannot continue."""
    payload = ReportFailurePayload(
        summary=summary,
        error=error,
        failure_category=FailureCategory(failure_category),
        failed_tool_name=failed_tool_name,
        failed_args_signature=failed_args_signature,
        is_recoverable=is_recoverable,
        recommended_action=RecoveryAction(recommended_action),
    )
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


INTERNAL_SUB_AGENT_TOOLS = [
    tool_read_scratchpad,
    tool_write_scratchpad,
    tool_write_plan,
    tool_exit_plan_mode,
    tool_task_stop,
    tool_report_failure,
    tool_task_complete,
]
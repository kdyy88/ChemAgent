from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScratchpadKind(str, Enum):
    context = "context"
    report = "report"
    note = "note"


class FailureCategory(str, Enum):
    infrastructure = "infrastructure"
    validation = "validation"
    schema = "schema"
    policy = "policy"
    unsupported_tool = "unsupported_tool"
    timeout = "timeout"
    unknown = "unknown"


class RecoveryAction(str, Enum):
    continue_same_task = "continue"
    spawn_new_task = "spawn"
    abort = "abort"


class ScratchpadRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scratchpad_id: str = Field(description="Opaque scratchpad identifier.")
    kind: ScratchpadKind = Field(description="Scratchpad payload category.")
    summary: str = Field(default="", description="Short human-readable summary.")
    size_bytes: int = Field(default=0, ge=0, description="Payload size in bytes.")
    created_by: str = Field(default="system", description="Producer label.")


class PlanPointer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(description="Stable UUID for a file-backed plan artifact.")
    plan_file_ref: str = Field(description="Opaque filesystem-backed plan reference.")
    status: str = Field(default="draft", description="Plan lifecycle state.")
    summary: str = Field(default="", description="Compact plan summary safe for parent state/UI.")
    revision: int = Field(default=1, ge=1, description="Lightweight revision counter for the plan artifact.")


class SubtaskPointer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subtask_id: str = Field(description="Stable UUID for an active child task.")
    kind: str = Field(description="Subtask kind such as plan or execution.")
    status: str = Field(default="pending", description="Current child task lifecycle state.")
    plan_id: str | None = Field(default=None, description="Associated plan UUID when applicable.")
    plan_file_ref: str | None = Field(default=None, description="Associated plan file pointer when applicable.")
    summary: str = Field(default="", description="Compact subtask summary for parent state/UI.")


class SubAgentDelegation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subagent_type: str = Field(description="Sub-agent type / mode identifier.")
    task_directive: str = Field(min_length=5, max_length=1_000, description="Self-contained task directive.")
    artifact_pointers: list[str] = Field(default_factory=list, description="Artifact identifiers inherited from the parent graph.")
    scratchpad_refs: list[ScratchpadRef] = Field(default_factory=list, description="Opaque references to long-form background material.")
    active_smiles: str = Field(default="", description="Verified active SMILES inherited from the parent graph.")
    active_artifact_id: str = Field(default="", description="Current active artifact pointer inherited from the parent graph.")
    molecule_workspace_summary: str = Field(default="", description="Compact parent workspace summary for grounding.")
    inline_context: str = Field(default="", max_length=1_500, description="Short fallback context when background is too small to justify scratchpad storage.")


class TaskCompletePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(default="", description="Compact completion summary for the parent agent.")
    produced_artifact_ids: list[str] = Field(default_factory=list, description="Artifact ids created or selected during the sub-task.")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Structured completion metrics.")
    advisory_active_smiles: str = Field(default="", description="Optional advisory active SMILES for the parent to consider.")


class ExitPlanModePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="plan_pending_approval", description="Terminal status indicating the plan is ready for approval.")
    plan: PlanPointer = Field(description="Stable pointer to the generated plan artifact.")
    summary: str = Field(default="", description="Compact planning summary for parent state/UI.")
    requires_approval: bool = Field(default=True, description="Whether the parent must route this result through approval.")


class ReportFailurePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="failed", description="Terminal status for structured child failure.")
    summary: str = Field(default="", description="Compact failure summary for the parent.")
    error: str = Field(default="", description="Detailed error text or latest exception summary.")
    failure_category: FailureCategory = Field(default=FailureCategory.unknown, description="Classified failure category.")
    failed_tool_name: str = Field(default="", description="Tool name involved in the failure, when applicable.")
    failed_args_signature: str = Field(default="", description="Normalized signature of the failing tool args.")
    is_recoverable: bool = Field(default=False, description="Whether the task can theoretically be retried or repaired.")
    recommended_action: RecoveryAction = Field(default=RecoveryAction.spawn_new_task, description="Recommended parent action after the failure.")


class TaskStopPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="stopped", description="Terminal status for intentional child stop.")
    summary: str = Field(default="", description="Compact stop summary for the parent.")
    reason: str = Field(default="", description="Human-readable stop reason.")
    is_recoverable: bool = Field(default=False, description="Whether the task can theoretically be retried or repaired.")
    recommended_action: RecoveryAction = Field(default=RecoveryAction.abort, description="Recommended parent action after the stop.")


FailurePayload = ReportFailurePayload | TaskStopPayload


class AgentToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="Execution status: ok / plan_pending_approval / failed / stopped / error / timeout / protocol_error / policy_conflict.")
    mode: str = Field(description="Resolved sub-agent mode.")
    sub_thread_id: str | None = Field(default=None, description="Opaque sub-agent runtime thread id.")
    execution_task_id: str | None = Field(default=None, description="Stable UUID for an execution-phase child, when applicable.")
    delegation: SubAgentDelegation | None = Field(default=None, description="Normalized delegation payload used for execution.")
    completion: TaskCompletePayload | None = Field(default=None, description="Structured terminal payload returned by TaskComplete.")
    plan_pointer: PlanPointer | None = Field(default=None, description="Stable pointer to a file-backed plan awaiting approval.")
    failure: FailurePayload | None = Field(default=None, description="Structured stop-loss payload returned by the child.")
    produced_artifacts: list[dict[str, Any]] = Field(default_factory=list, description="Artifacts accumulated by sub-agent tools.")
    scratchpad_report_ref: ScratchpadRef | None = Field(default=None, description="Opaque reference to the final assistant report.")
    summary: str = Field(default="", description="Short summary safe to persist in parent conversation history.")
    advisory_active_smiles: str | None = Field(default=None, description="Optional advisory active SMILES reported by the child.")
    error: str | None = Field(default=None, description="Error text when execution failed.")


def format_delegation_prompt(delegation: SubAgentDelegation) -> str:
    lines = [
        "<delegation>",
        f"subagent_type: {delegation.subagent_type}",
        f"task_directive: {delegation.task_directive}",
    ]

    if delegation.active_smiles:
        lines.append(f"active_smiles: {delegation.active_smiles}")
    if delegation.active_artifact_id:
        lines.append(f"active_artifact_id: {delegation.active_artifact_id}")
    if delegation.artifact_pointers:
        lines.append("artifact_pointers:")
        for artifact_id in delegation.artifact_pointers:
            lines.append(f"- {artifact_id}")
    if delegation.scratchpad_refs:
        lines.append("scratchpad_refs:")
        for ref in delegation.scratchpad_refs:
            summary = ref.summary or "(no summary)"
            lines.append(f"- {ref.scratchpad_id} [{ref.kind.value}] {summary}")
    if delegation.molecule_workspace_summary:
        lines.append("molecule_workspace_summary:")
        lines.append(delegation.molecule_workspace_summary)
    if delegation.inline_context:
        lines.append("inline_context:")
        lines.append(delegation.inline_context)

    lines.append("</delegation>")
    lines.append("若需要读取 scratchpad_refs 的全文，请调用 tool_read_scratchpad。")
    lines.append("执行子任务完成时调用 tool_task_complete；规划阶段完成时调用 tool_exit_plan_mode；若无法继续，请调用 tool_report_failure 或 tool_task_stop。")
    return "\n".join(lines)
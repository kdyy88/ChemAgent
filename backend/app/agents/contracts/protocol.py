from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.schemas.workflow import (
    FailureCategory,
    PlanPointer,
    RecoveryAction,
    ScratchpadKind,
    ScratchpadRef,
    SubtaskPointer,
)


# ---------------------------------------------------------------------------
# Chem LSP Protocol — tool return contracts for state-driven writes
# ---------------------------------------------------------------------------

class NodeUpdate(BaseModel):
    """L1 tools: update diagnostics / status on an existing molecule node.

    Diagnostics are **merged** with any existing values — non-destructive.
    If *status* is None the existing node status is preserved.
    """
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(description="Target molecule's artifact_id in molecule_tree.")
    diagnostics: dict[str, Any] = Field(default_factory=dict, description="Key-value diagnostic metrics to merge (e.g. logP, mw, warnings).")
    status: str | None = Field(default=None, description="New MoleculeStatus; None preserves current status.")


class NodeCreate(BaseModel):
    """L2/L3 tools: register a new molecule branch in the tree.

    The executor will append *artifact_id* to viewport.focused_artifact_ids.
    """
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(description="Unique artifact ID for the new molecule (e.g. mol_01H...).")
    smiles: str = Field(description="Canonical SMILES of the new molecule.")
    parent_id: str | None = Field(default=None, description="Artifact ID of the precursor molecule (for scaffold-hop lineage).")
    diagnostics: dict[str, Any] = Field(default_factory=dict, description="Initial diagnostic metrics.")
    status: str = Field(default="staged", description="Initial MoleculeStatus.")


# ---------------------------------------------------------------------------
# Sub-agent protocol
# ---------------------------------------------------------------------------

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
    xml_report: str = Field(default="", description="Validated XML report safe to persist in parent conversation history.")


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


def build_subagent_report_xml(
    *,
    status: str,
    summary: str,
    artifact_ids: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
    advisory_active_smiles: str = "",
) -> str:
    root = ET.Element("subagent_report")
    ET.SubElement(root, "status").text = str(status or "completed").strip() or "completed"
    ET.SubElement(root, "summary").text = str(summary or "").strip()

    generated_artifacts = ET.SubElement(root, "generated_artifacts")
    for artifact_id in artifact_ids or []:
        normalized = str(artifact_id or "").strip()
        if normalized:
            ET.SubElement(generated_artifacts, "artifact_id").text = normalized

    metrics_node = ET.SubElement(root, "metrics")
    for key, value in (metrics or {}).items():
        metric = ET.SubElement(metrics_node, "metric", key=str(key))
        metric.text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    ET.SubElement(root, "advisory_active_smiles").text = str(advisory_active_smiles or "").strip()
    return ET.tostring(root, encoding="unicode")


def parse_subagent_report_xml(xml_report: str) -> TaskCompletePayload:
    try:
        root = ET.fromstring(str(xml_report or "").strip())
    except ET.ParseError as exc:
        raise ValueError(f"Invalid subagent_report XML: {exc}") from exc

    if root.tag != "subagent_report":
        raise ValueError("Invalid subagent_report XML: root tag must be <subagent_report>")

    summary = (root.findtext("summary") or "").strip()
    artifact_ids = [
        (node.text or "").strip()
        for node in root.findall("./generated_artifacts/artifact_id")
        if (node.text or "").strip()
    ]
    metrics: dict[str, Any] = {}
    for node in root.findall("./metrics/metric"):
        key = str(node.attrib.get("key") or "").strip()
        if not key:
            continue
        raw_value = (node.text or "").strip()
        if not raw_value:
            metrics[key] = ""
            continue
        try:
            metrics[key] = json.loads(raw_value)
        except json.JSONDecodeError:
            metrics[key] = raw_value

    return TaskCompletePayload(
        summary=summary,
        produced_artifact_ids=artifact_ids,
        metrics=metrics,
        advisory_active_smiles=(root.findtext("advisory_active_smiles") or "").strip(),
        xml_report=ET.tostring(root, encoding="unicode"),
    )


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
    lines.append("执行子任务完成时调用 tool_task_complete，并传入 `<subagent_report>...</subagent_report>` XML；规划阶段完成时调用 tool_exit_plan_mode；若无法继续，请调用 tool_report_failure 或 tool_task_stop。")
    return "\n".join(lines)
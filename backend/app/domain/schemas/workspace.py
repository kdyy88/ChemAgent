from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


RuleKind = Literal["preserve", "require", "note", "target"]
MoleculeNodeStatus = Literal["active", "candidate", "archived", "stale"]
RelationKind = Literal["derived_from", "compared_to"]
AsyncJobStatus = Literal["queued", "running", "completed", "failed", "stale", "cancelled"]
ScenarioKind = Literal["scaffold_hop_mvp"]
ApprovalState = Literal["not_required", "pending", "approved", "rejected", "modified"]
WorkspaceDeltaScope = Literal["graph", "viewport", "rules", "jobs", "workspace"]
WorkspaceDeltaOpKind = Literal[
    "node_upsert",
    "relation_upsert",
    "viewport_set",
    "rule_add",
    "job_upsert",
    "job_progress",
    "job_stale",
    "job_complete",
]


def new_workspace_id() -> str:
    return f"ws_{uuid4().hex[:12]}"


def new_rule_id() -> str:
    return f"rule_{uuid4().hex[:12]}"


def new_node_id() -> str:
    return f"mol_{uuid4().hex[:12]}"


def new_relation_id() -> str:
    return f"rel_{uuid4().hex[:12]}"


class RuleSetEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(default_factory=new_rule_id)
    kind: RuleKind
    text: str = Field(min_length=1)
    normalized_value: str = Field(default="")
    source: str = Field(default="user_prompt")
    created_by: str = Field(default="agent")


class MoleculeNodeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(default_factory=new_node_id)
    handle: str = Field(min_length=1)
    canonical_smiles: str = Field(min_length=1)
    display_name: str = Field(default="")
    parent_node_id: str | None = Field(default=None)
    origin: str = Field(default="")
    status: MoleculeNodeStatus = Field(default="candidate")
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list)
    hover_text: str = Field(default="")


class MoleculeRelationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_id: str = Field(default_factory=new_relation_id)
    relation_kind: RelationKind = Field(default="derived_from")
    source_node_id: str
    target_node_id: str
    label: str = Field(default="")


class WorkspaceViewport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focused_handles: list[str] = Field(default_factory=list)
    reference_handle: str | None = Field(default=None)


class SemanticHandleBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str
    node_id: str
    bound_at_version: int = Field(ge=0)


class AsyncJobPointer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    job_type: str
    target_handle: str
    target_node_id: str
    base_workspace_version: int = Field(ge=0)
    requested_at_version: int = Field(default=0, ge=0)
    completed_at_version: int | None = Field(default=None, ge=0)
    status: AsyncJobStatus = Field(default="queued")
    approval_state: ApprovalState = Field(default="not_required")
    job_args: dict[str, Any] = Field(default_factory=dict)
    stale_reason: str = Field(default="")
    artifact_id: str | None = Field(default=None)
    result_summary: str = Field(default="")


class WorkspaceDeltaOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: WorkspaceDeltaOpKind
    key: str
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkspaceDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_version: int = Field(ge=0)
    version: int = Field(ge=0)
    scope: WorkspaceDeltaScope = Field(default="workspace")
    ops: list[WorkspaceDeltaOp] = Field(default_factory=list)


class WorkspaceEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    version: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkspaceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    workspace_id: str = Field(default_factory=new_workspace_id)
    version: int = Field(default=0, ge=0)
    scenario_kind: ScenarioKind | None = Field(default=None)
    root_handle: str | None = Field(default=None)
    candidate_handles: list[str] = Field(default_factory=list)
    active_view_id: str | None = Field(default=None)
    nodes: dict[str, MoleculeNodeRecord] = Field(default_factory=dict)
    relations: dict[str, MoleculeRelationRecord] = Field(default_factory=dict)
    handle_bindings: dict[str, SemanticHandleBinding] = Field(default_factory=dict)
    viewport: WorkspaceViewport = Field(default_factory=WorkspaceViewport)
    rules: list[RuleSetEntry] = Field(default_factory=list)
    async_jobs: dict[str, AsyncJobPointer] = Field(default_factory=dict)

    def active_candidate_count(self) -> int:
        return len(self.candidate_handles)

    def assert_mvp_shape(self) -> None:
        if self.root_handle is not None and self.root_handle not in self.handle_bindings:
            raise ValueError("workspace root_handle must reference an existing handle")
        if len(self.candidate_handles) > 3:
            raise ValueError("workspace candidate_handles exceeds MVP limit of 3")
        for handle in self.candidate_handles:
            if handle not in self.handle_bindings:
                raise ValueError(f"workspace candidate handle is unbound: {handle}")


class CreateRootMoleculeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_smiles: str = Field(min_length=1)
    display_name: str = Field(default="")
    handle: str = Field(default="root_molecule")
    hover_text: str = Field(default="")
    node_id: str | None = Field(default=None)
    artifact_ids: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RegisterRuleCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RuleKind
    text: str = Field(min_length=1)
    normalized_value: str = Field(default="")
    source: str = Field(default="user_prompt")
    created_by: str = Field(default="agent")


class CreateCandidateBranchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_handle: str = Field(min_length=1)
    handle: str = Field(min_length=1)
    canonical_smiles: str = Field(min_length=1)
    display_name: str = Field(default="")
    origin: str = Field(default="scaffold_hop")
    hover_text: str = Field(default="")
    node_id: str | None = Field(default=None)
    artifact_ids: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class SetViewportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focused_handles: list[str] = Field(min_length=1)
    reference_handle: str | None = Field(default=None)


class StartAsyncJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    job_type: str
    target_handle: str
    approval_state: ApprovalState = Field(default="not_required")
    job_args: dict[str, Any] = Field(default_factory=dict)


class MarkAsyncJobProgressCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    result_summary: str = Field(default="")
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class MarkAsyncJobStaleCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    stale_reason: str = Field(min_length=1)
    result_summary: str = Field(default="")


class ApplyAsyncJobResultCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    artifact_id: str | None = Field(default=None)
    hover_text: str = Field(default="")
    result_summary: str = Field(default="")


class PatchNodeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    status: MoleculeNodeStatus | None = Field(default=None)
    hover_text: str = Field(default="")
    artifact_id: str | None = Field(default=None)

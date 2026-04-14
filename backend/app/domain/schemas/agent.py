from __future__ import annotations

import operator
from typing import Any, Annotated, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import NotRequired, TypedDict

from app.domain.schemas.workspace import WorkspaceDelta, WorkspaceEventRecord, WorkspaceProjection


TaskStatus = Literal["pending", "in_progress", "completed", "failed"]
MoleculeStatus = Literal["staged", "exploring", "rejected", "lead"]


# ---------------------------------------------------------------------------
# 1. 项目黑板 (IDE README) — 驻留在根状态，由 Checkpointer 自动持久化
# ---------------------------------------------------------------------------
class ProjectScratchpad(TypedDict):
    research_goal: NotRequired[str]             # 本次会话的研究总目标
    established_rules: NotRequired[list[str]]   # 通过实验归纳出的化学规则
    failed_attempts: NotRequired[list[str]]     # 已验证失败的路径，防止重复踩坑


# ---------------------------------------------------------------------------
# 2. 分子节点 (Git for Molecules) — molecule_tree 的叶节点
# ---------------------------------------------------------------------------
class MoleculeNode(TypedDict):
    artifact_id: str                                 # 唯一工件指针 (e.g., mol_01H...)
    smiles: str                                      # 化学 DSL 源码
    parent_id: NotRequired[str | None]               # 演进血缘 (骨架跃迁的起点)
    creation_operation: NotRequired[str]             # e.g., "scaffold_hop_to_indole"
    status: NotRequired[MoleculeStatus]
    diagnostics: NotRequired[dict[str, Any]]         # LSP 诊断结果 (e.g., {"logP": 2.5, "warnings": []})
    aliases: NotRequired[list[str]]
    molecular_weight: NotRequired[float | str]


# ---------------------------------------------------------------------------
# 3. 多光标视口 (Viewport) — LLM 当前正在对比/操作的分子集合
# ---------------------------------------------------------------------------
class WorkspaceViewport(TypedDict):
    focused_artifact_ids: list[str]                  # 当前焦点分子集
    reference_artifact_id: NotRequired[str | None]   # 参考母本


# ---------------------------------------------------------------------------
# 4. molecule_tree reducer — upsert 语义，支持单节点增量更新
#    LangGraph 在第一次写入时以 (None, update) 调用 reducer，需防御处理
# ---------------------------------------------------------------------------
def merge_molecule_tree(
    existing: dict[str, MoleculeNode] | None,
    update: dict[str, MoleculeNode],
) -> dict[str, MoleculeNode]:
    if existing is None:
        return update
    return {**existing, **update}


# ---------------------------------------------------------------------------
# 5a. File read state — tracks mtime of files read by the LLM this session.
#     Stored in ChemState so the checkpointer persists and can time-travel it.
#     Reducer: upsert (entries from new reads are merged on top of existing).
# ---------------------------------------------------------------------------
class FileReadEntry(TypedDict):
    mtime: float


def merge_file_read_state(
    existing: dict[str, FileReadEntry] | None,
    update: dict[str, FileReadEntry],
) -> dict[str, FileReadEntry]:
    if existing is None:
        return update
    return {**existing, **update}


# ---------------------------------------------------------------------------
# Legacy stub — 保留导出符号，避免 Phase 2 之前的 ImportError
# MoleculeWorkspaceEntry 已被 MoleculeNode 取代；Phase 2 将移除全部引用
# ---------------------------------------------------------------------------
class MoleculeWorkspaceEntry(TypedDict):
    key: str


# ---------------------------------------------------------------------------
# 保留原有定义
# ---------------------------------------------------------------------------
class Task(TypedDict):
    id: str
    description: str
    status: TaskStatus
    summary: NotRequired[str]
    completion_revision: NotRequired[int]


class SubtaskStatePointer(TypedDict):
    kind: str
    status: str
    summary: NotRequired[str]
    plan_id: NotRequired[str]
    plan_file_ref: NotRequired[str]
    execution_task_id: NotRequired[str]


class PendingWorkerTask(TypedDict):
    task_id: str
    task_name: str
    tool_name: str
    workspace_job_id: str
    workspace_target_handle: NotRequired[str]
    project_id: NotRequired[str]
    workspace_id: NotRequired[str]
    workspace_version: NotRequired[int]


# ---------------------------------------------------------------------------
# 5. ChemState — 系统状态机核心
# ---------------------------------------------------------------------------
class ChemState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    selected_model: str | None

    # --- Canonical workspace state ---
    workspace_projection: WorkspaceProjection | dict[str, Any]
    workspace_delta: NotRequired[WorkspaceDelta | dict[str, Any] | None]
    workspace_events: NotRequired[list[WorkspaceEventRecord | dict[str, Any]]]

    # --- Legacy compatibility mirrors ---
    viewport: NotRequired[WorkspaceViewport]
    molecule_tree: NotRequired[Annotated[dict[str, MoleculeNode], merge_molecule_tree]]
    scratchpad: ProjectScratchpad
    read_file_state: Annotated[dict[str, FileReadEntry], merge_file_read_state]

    artifacts: Annotated[list[dict], operator.add]

    tasks: list[Task]
    is_complex: bool
    evidence_revision: int
    sub_agent_result: dict[str, Any] | None
    active_subtasks: dict[str, SubtaskStatePointer]
    active_subtask_id: str | None
    subtask_control: dict[str, Any] | None
    artifact_expiry_warning: NotRequired[str | None]
    skills_enabled: bool
    scenario_kind: NotRequired[str | None]
    active_handle: NotRequired[str | None]
    candidate_handles: NotRequired[list[str]]
    candidate_generation_status: NotRequired[str | None]
    approval_context: NotRequired[dict[str, Any] | None]
    pending_approval_job_ids: NotRequired[list[str]]
    last_workspace_version: NotRequired[int]
    pending_worker_tasks: NotRequired[list[PendingWorkerTask]]


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_complex: bool = Field(
        description="任务是否包含多个子目标、明显的顺序依赖，或通常需要至少三次工具调用。",
    )


class PlannedTaskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="单个可执行子任务的简短标签。要求具体明确，但必须非常精炼，建议 4-12 个中文字符，避免长句和细节。")


class PlanStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[PlannedTaskItem] = Field(description="按顺序排列的 3-8 个子任务，每项都必须是简短标签式描述。")

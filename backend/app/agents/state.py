from __future__ import annotations

import operator
from typing import Any, Annotated, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import NotRequired
from typing_extensions import TypedDict


TaskStatus = Literal["pending", "in_progress", "completed", "failed"]


class Task(TypedDict):
    id: str
    description: str
    status: TaskStatus
    summary: NotRequired[str]
    completion_revision: NotRequired[int]


class MoleculeWorkspaceEntry(TypedDict):
    key: str
    primary_name: NotRequired[str]
    aliases: NotRequired[list[str]]
    canonical_smiles: NotRequired[str]
    isomeric_smiles: NotRequired[str]
    formula: NotRequired[str]
    molecular_weight: NotRequired[float | str]
    iupac_name: NotRequired[str]
    artifact_ids: NotRequired[list[str]]
    parent_artifact_ids: NotRequired[list[str]]
    scaffold_smiles: NotRequired[str]
    generic_scaffold_smiles: NotRequired[str]
    descriptors: NotRequired[dict]
    lipinski: NotRequired[dict]
    validation: NotRequired[dict]
    source_tools: NotRequired[list[str]]


class SubtaskStatePointer(TypedDict):
    kind: str
    status: str
    summary: NotRequired[str]
    plan_id: NotRequired[str]
    plan_file_ref: NotRequired[str]
    execution_task_id: NotRequired[str]


class ChemState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    selected_model: str | None
    active_smiles: str | None
    artifacts: Annotated[list[dict], operator.add]
    molecule_workspace: list[MoleculeWorkspaceEntry]
    tasks: list[Task]
    is_complex: bool
    evidence_revision: int
    sub_agent_result: dict[str, Any] | None
    active_subtasks: dict[str, SubtaskStatePointer]
    active_subtask_id: str | None
    subtask_control: dict[str, Any] | None
    artifact_expiry_warning: NotRequired[str | None]


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

    tasks: list[PlannedTaskItem] = Field(description="按顺序排列的 3-5 个子任务，每项都必须是简短标签式描述。")
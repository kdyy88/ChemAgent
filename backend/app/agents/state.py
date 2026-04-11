from __future__ import annotations

import operator
from typing import Any, Annotated, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
# Pydantic schemas are defined in domain/schemas/agent.py and re-exported here
# for backward compatibility.
from app.domain.schemas.agent import PlannedTaskItem, PlanStructure, RouteDecision  # noqa: F401
from typing_extensions import NotRequired
from typing_extensions import TypedDict


TaskStatus = Literal["pending", "in_progress", "completed", "failed"]
SessionMode = Literal["general", "explore", "plan"]


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
    mode: SessionMode
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


# RouteDecision, PlannedTaskItem, PlanStructure are defined in
# app.domain.schemas.agent and imported above.
from __future__ import annotations

import operator
from typing import Annotated, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict


TaskStatus = Literal["pending", "in_progress", "completed", "failed"]


class Task(TypedDict):
    id: str
    description: str
    status: TaskStatus


class ChemState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    active_smiles: str | None
    artifacts: Annotated[list[dict], operator.add]
    tasks: list[Task]
    is_complex: bool


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_complex: bool = Field(
        description="任务是否包含多个子目标、明显的顺序依赖，或通常需要至少三次工具调用。",
    )


class PlannedTaskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="单个可执行子任务，要求具体明确。")


class PlanStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[PlannedTaskItem] = Field(description="按顺序排列的 3-5 个子任务。")
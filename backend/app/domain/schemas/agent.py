"""
Agent domain schemas — state, task tracking, and routing models.

These are the canonical definitions.  app/agents/state.py re-exports from here
for backward compatibility.
"""
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

    description: str = Field(description="单个可执行子任务的简短标签。要求具体明确，但必须非常精炼，建议 4-12 个中文字符，避免长句和细节。")


class PlanStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[PlannedTaskItem] = Field(description="按顺序排列的 3-5 个子任务，每项都必须是简短标签式描述。")

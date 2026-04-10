"""
Pydantic schemas for agent structured outputs.

Used by planner and router nodes to parse LLM-generated structured responses.
These are passed to ``ChatOpenAI.with_structured_output()`` and must have
``model_config = ConfigDict(extra="forbid")`` to catch schema drift.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RouteDecision(BaseModel):
    """Output schema for the task router node."""
    model_config = ConfigDict(extra="forbid")

    is_complex: bool = Field(
        description="任务是否包含多个子目标、明显的顺序依赖，或通常需要至少三次工具调用。",
    )


class PlannedTaskItem(BaseModel):
    """A single executable subtask in a planner-generated task list."""
    model_config = ConfigDict(extra="forbid")

    description: str = Field(
        description="单个可执行子任务的简短标签。要求具体明确，但必须非常精炼，建议 4-12 个中文字符，避免长句和细节。"
    )


class PlanStructure(BaseModel):
    """Output schema for the planner node."""
    model_config = ConfigDict(extra="forbid")

    tasks: list[PlannedTaskItem] = Field(
        description="按顺序排列的 3-5 个子任务，每项都必须是简短标签式描述。"
    )

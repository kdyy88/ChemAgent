"""
Pydantic request/response schemas for the HTTP API layer.

These are the inbound message contracts (SSE chat, approval flow).
Response-side schemas that are tightly coupled to route handlers remain
in ``app.api.sse.chat``.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class HistoryMessage(BaseModel):
    """A single turn in the conversation history."""
    role: str    # "human" or "assistant"
    content: str


class PendingPlanContext(BaseModel):
    """Plan content forwarded with a follow-up message while approval is pending."""

    plan_id: str = Field(..., description="待审批计划的稳定 ID")
    plan_file_ref: str | None = Field(default=None, description="计划文件引用")
    summary: str | None = Field(default=None, description="计划摘要")
    content: str = Field(..., description="计划 Markdown 正文")


class StreamChatRequest(BaseModel):
    """Request body for POST /stream."""
    message: str = Field(..., description="用户输入的化学问题或指令")
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    turn_id: str = Field(default_factory=lambda: uuid4().hex)
    model: str | None = Field(default=None, description="本轮对话使用的模型 ID（可选）")
    active_smiles: str | None = Field(
        default=None,
        description="当前画布上已激活的 SMILES（可选；来自前端状态）",
    )
    mode: Literal["general", "explore", "plan"] = Field(
        default="general",
        description="前端显式指定的会话模式（'general' | 'explore' | 'plan'）",
    )
    interrupt_context: dict | None = Field(
        default=None,
        description="LangGraph 原生 HITL 恢复上下文；至少包含 interrupt_id",
    )
    history: list[HistoryMessage] = Field(
        default_factory=list,
        description="前序对话轮次消息，按时间正序排列（human/assistant 交替）",
    )
    pending_plan_context: PendingPlanContext | None = Field(
        default=None,
        description="当存在待审批计划且用户继续发消息时，前端附带的计划正文上下文",
    )


class ApproveToolRequest(BaseModel):
    """Payload sent by the frontend ApprovalCard after the user makes a decision."""
    session_id: str = Field(..., description="会话 ID，用于定位挂起的图检查点")
    turn_id: str = Field(default_factory=lambda: uuid4().hex)
    plan_id: str | None = Field(
        default=None,
        description="计划审批流的稳定 plan_id。提供后表示此次审批针对计划文件而非普通工具断点。",
    )
    action: str = Field(..., description='"approve" | "reject" | "modify"')
    model: str | None = Field(
        default=None,
        description="批准执行时希望使用的模型 ID（可选；用于计划执行子智能体）",
    )
    args: dict | None = Field(
        default=None,
        description="修改后的工具参数（仅在 action=modify 时有效）",
    )

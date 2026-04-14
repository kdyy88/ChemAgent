from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


SessionControlType = Literal["session.start", "session.resume"]
UserMessageType = Literal["user.message", "session.clear"]
HeartbeatClientType = Literal["pong"]
ServerEventType = Literal[
    "ping",
    "session.started",
    "run.started",
    "run.finished",
    "run.failed",
    "turn.status",
    "assistant.message",
    "assistant.delta",
    "assistant.done",
    "tool.call",
    "tool.result",
    "workspace.snapshot",
    "workspace.delta",
    "molecule.upserted",
    "relation.upserted",
    "viewport.changed",
    "rules.updated",
    "job.started",
    "job.progress",
    "job.completed",
    "job.failed",
    "artifact.ready",
]


class SessionControlMessage(BaseModel):
    type: SessionControlType
    session_id: str | None = None
    agent_models: dict[str, str] | None = None


class UserMessage(BaseModel):
    type: UserMessageType
    content: str
    turn_id: str | None = None
    agent_models: dict[str, str] | None = None


class HeartbeatMessage(BaseModel):
    type: HeartbeatClientType


class EventEnvelope(BaseModel):
    type: ServerEventType
    session_id: str | None = None
    turn_id: str | None = None
    run_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            **self.payload,
        }
        if self.session_id is not None:
            data["session_id"] = self.session_id
        if self.turn_id is not None:
            data["turn_id"] = self.turn_id
        if self.run_id is not None:
            data["run_id"] = self.run_id
        return data


class HistoryMessage(BaseModel):
    role: str
    content: str


class StreamChatRequest(BaseModel):
    message: str = Field(..., description="用户输入的化学问题或指令")
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    turn_id: str = Field(default_factory=lambda: uuid4().hex)
    model: str | None = Field(default=None, description="本轮对话使用的模型 ID（可选）")
    active_smiles: str | None = Field(
        default=None,
        description="当前画布上已激活的 SMILES（可选；来自前端状态）",
    )
    interrupt_context: dict | None = Field(
        default=None,
        description="LangGraph 原生 HITL 恢复上下文；至少包含 interrupt_id",
    )
    history: list[HistoryMessage] = Field(
        default_factory=list,
        description="前序对话轮次消息，按时间正序排列（human/assistant 交替）",
    )
    skills_enabled: bool = Field(
        default=False,
        description="是否在本轮对话中启用 Skills 模块（前端开关控制，默认关闭）",
    )


class ApproveToolRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID，用于定位挂起的图检查点")
    turn_id: str = Field(default_factory=lambda: uuid4().hex)
    plan_id: str | None = Field(default=None, description="计划审批流的稳定 plan_id。提供后表示此次审批针对计划文件而非普通工具断点。")
    action: str = Field(..., description='"approve" | "reject" | "modify"')
    args: dict | None = Field(
        default=None,
        description="修改后的工具参数（仅在 action=modify 时有效）",
    )


class PendingJobsRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID，用于定位持久化 LangGraph 状态")
    turn_id: str = Field(default_factory=lambda: uuid4().hex)


class MvpConformerSmokeRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    turn_id: str = Field(default_factory=lambda: uuid4().hex)
    smiles: str = Field(..., description="用于 smoke test 的标准 SMILES")
    name: str = Field(default="", description="可选化合物名称")
    forcefield: str = Field(default="mmff94", description="Open Babel 力场")
    steps: int = Field(default=500, ge=10, le=5000, description="优化步数")


class ModelCatalogItem(BaseModel):
    id: str
    label: str
    is_default: bool = False
    is_reasoning: bool = False
    max_context_tokens: int


class ModelCatalogResponse(BaseModel):
    source: str
    models: list[ModelCatalogItem]
    warning: str | None = None


class SmilesRequest(BaseModel):
    smiles: str


class AnalyzeRequest(BaseModel):
    smiles: str
    name: str = ""


class DescriptorsRequest(BaseModel):
    smiles: str = Field(..., description="Standard SMILES string")
    name: str = Field("", description="Optional compound name")


class SimilarityRequest(BaseModel):
    smiles1: str = Field(..., description="First molecule SMILES")
    smiles2: str = Field(..., description="Second molecule SMILES")
    radius: int = Field(2, ge=1, le=6, description="Morgan FP radius (default 2 = ECFP4)")
    n_bits: int = Field(2048, description="Fingerprint bit length")


class SubstructureRequest(BaseModel):
    smiles: str = Field(..., description="Target molecule SMILES")
    smarts_pattern: str = Field(..., description="SMARTS pattern to search for")


class ScaffoldRequest(BaseModel):
    smiles: str = Field(..., description="Standard SMILES string")


class ScratchpadResponse(BaseModel):
    scratchpad_id: str
    kind: str
    summary: str
    size_bytes: int
    created_by: str
    content: str

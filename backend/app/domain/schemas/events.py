from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.schemas.workspace import WorkspaceDelta, WorkspaceProjection


SessionControlType = Literal["session.start", "session.resume"]
UserMessageType = Literal["user.message", "session.clear"]
HeartbeatClientType = Literal["pong"]
ApprovalAction = Literal["approve", "reject", "modify"]

ServerEventType = Literal[
    "ping",
    "session.started",
    "run.started",
    "run_started",
    "run.finished",
    "run.failed",
    "turn.status",
    "assistant.message",
    "assistant.delta",
    "assistant.done",
    "token",
    "tool.call",
    "tool.result",
    "tool_start",
    "tool_end",
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
    "job.stale",
    "artifact.ready",
    "artifact",
    "thinking",
    "task_update",
    "interrupt",
    "approval_required",
    "done",
    "error",
]


class WorkspaceDeltaPayload(BaseModel):
    delta: WorkspaceDelta


class JobEventPayload(BaseModel):
    job_id: str
    job_type: str | None = None
    status: str
    target_handle: str | None = None
    version: int | None = None
    artifact_id: str | None = None
    summary: str | None = None
    stale_reason: str | None = None


class ApprovalRequiredPayload(BaseModel):
    approval_id: str | None = None
    target_job_id: str | None = None
    tool_name: str | None = None
    action_hint: str | None = None
    allowed_modify_keys: list[str] = Field(default_factory=list)
    message: str | None = None


class ArtifactReadyPayload(BaseModel):
    artifact_id: str
    kind: str | None = None
    title: str | None = None
    target_handle: str | None = None
    version: int | None = None


class WorkspaceSnapshotResponse(BaseModel):
    session_id: str
    workspace: WorkspaceProjection
    version: int
    pending_job_count: int = 0


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
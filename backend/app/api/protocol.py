from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


SessionControlType = Literal["session.start", "session.resume"]
UserMessageType = Literal[
    "user.message",
    "session.clear",
    "plan.approve",
    "plan.reject",
    "plan.modify",
]
HeartbeatClientType = Literal["pong"]
ServerEventType = Literal[
    "ping",
    "session.started",
    "run.started",
    "run.finished",
    "run.failed",
    "turn.status",
    "assistant.message",
    "assistant.delta",   # streaming token chunk (real-time)
    "tool.call",
    "tool.result",
    # ── HITL state-machine events ──
    "plan.proposed",
    "plan.status",
    "todo.progress",
    # ── Reasoning / thinking tokens ──
    "thinking.delta",
    # ── Multi-agent quality-control ──
    "review.status",
    # ── Reconnect snapshot ──
    "state.snapshot",
    # ── Settings ──
    "settings.updated",
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

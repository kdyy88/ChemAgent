from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ScratchpadKind(str, Enum):
    context = "context"
    report = "report"
    note = "note"


class FailureCategory(str, Enum):
    infrastructure = "infrastructure"
    validation = "validation"
    schema = "schema"
    policy = "policy"
    unsupported_tool = "unsupported_tool"
    timeout = "timeout"
    unknown = "unknown"


class RecoveryAction(str, Enum):
    continue_same_task = "continue"
    spawn_new_task = "spawn"
    abort = "abort"


class ScratchpadRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scratchpad_id: str = Field(description="Opaque scratchpad identifier.")
    kind: ScratchpadKind = Field(description="Scratchpad payload category.")
    summary: str = Field(default="", description="Short human-readable summary.")
    size_bytes: int = Field(default=0, ge=0, description="Payload size in bytes.")
    created_by: str = Field(default="system", description="Producer label.")


class PlanPointer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(description="Stable UUID for a file-backed plan artifact.")
    plan_file_ref: str = Field(description="Opaque filesystem-backed plan reference.")
    status: str = Field(default="draft", description="Plan lifecycle state.")
    summary: str = Field(default="", description="Compact plan summary safe for parent state/UI.")
    revision: int = Field(default=1, ge=1, description="Lightweight revision counter for the plan artifact.")


class SubtaskPointer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subtask_id: str = Field(description="Stable UUID for an active child task.")
    kind: str = Field(description="Subtask kind such as plan or execution.")
    status: str = Field(default="pending", description="Current child task lifecycle state.")
    plan_id: str | None = Field(default=None, description="Associated plan UUID when applicable.")
    plan_file_ref: str | None = Field(default=None, description="Associated plan file pointer when applicable.")
    summary: str = Field(default="", description="Compact subtask summary for parent state/UI.")
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


ArtifactEncoding = Literal["base64", "utf8", "json"]
ToolStatus = Literal["success", "error"]


class ToolArtifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: f"artifact_{uuid4().hex}")
    kind: str
    mime_type: str
    data: str | dict[str, Any] | list[Any] | None = None
    encoding: ArtifactEncoding = "utf8"
    title: str | None = None
    description: str | None = None


class ToolExecutionResult(BaseModel):
    result_id: str = Field(default_factory=lambda: f"result_{uuid4().hex}")
    status: ToolStatus
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ToolArtifact] = Field(default_factory=list)
    retry_hint: str | None = None
    error_code: str | None = None
    tool_name: str | None = None

    def to_model_payload(self) -> str:
        payload = self.model_dump(exclude_none=True)
        payload["artifacts"] = [
            {
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind,
                "mime_type": artifact.mime_type,
                "encoding": artifact.encoding,
                "title": artifact.title,
                "description": artifact.description,
                "has_data": True,
            }
            for artifact in self.artifacts
        ]
        return json.dumps(payload, ensure_ascii=False)


@dataclass
class ToolResultStore:
    _results: dict[str, tuple[float, ToolExecutionResult]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    ttl_seconds: int = 60 * 10

    def put(self, result: ToolExecutionResult) -> None:
        with self._lock:
            self._prune_locked()
            self._results[result.result_id] = (time.time(), result)

    def get(self, result_id: str | None) -> ToolExecutionResult | None:
        if not result_id:
            return None

        with self._lock:
            self._prune_locked()
            entry = self._results.get(result_id)
            if entry is None:
                return None
            return entry[1]

    def _prune_locked(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        expired = [key for key, (created_at, _value) in self._results.items() if created_at < cutoff]
        for key in expired:
            self._results.pop(key, None)





def parse_tool_payload(content: str | None) -> ToolExecutionResult | None:
    if not content:
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    try:
        return ToolExecutionResult.model_validate(payload)
    except Exception:
        return None


tool_result_store = ToolResultStore()

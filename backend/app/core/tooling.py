from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import threading
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Literal
from uuid import uuid4

from autogen.tools import Tool
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


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    display_name: str
    category: str
    reflection_hint: str | None
    func: Callable[..., Any]
    output_kinds: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def _normalize_result(self, raw: Any) -> ToolExecutionResult:
        if isinstance(raw, ToolExecutionResult):
            result = raw
        elif isinstance(raw, str):
            result = ToolExecutionResult(status="success", summary=raw)
        elif isinstance(raw, dict):
            result = ToolExecutionResult.model_validate(raw)
        else:
            result = ToolExecutionResult(
                status="success",
                summary="Tool executed successfully.",
                data={"value": raw},
            )

        if result.status == "error" and not result.retry_hint and self.reflection_hint:
            result.retry_hint = self.reflection_hint
        if not result.tool_name:
            result.tool_name = self.name
        return result

    def build_execution_callable(self) -> Callable[..., str]:
        @wraps(self.func)
        def wrapper(*args: Any, **kwargs: Any) -> str:
            result = self._normalize_result(self.func(*args, **kwargs))
            tool_result_store.put(result)
            return result.to_model_payload()

        wrapper.__signature__ = inspect.signature(self.func)
        wrapper.__annotations__ = getattr(self.func, "__annotations__", {}).copy()
        wrapper.__doc__ = self.description
        wrapper.__name__ = self.name
        return wrapper

    def to_autogen_tool(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            func_or_tool=self.build_execution_callable(),
        )

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "displayName": self.display_name,
            "category": self.category,
            "outputKinds": list(self.output_kinds),
            "tags": list(self.tags),
            "tool_schema": self.to_autogen_tool().tool_schema,
        }


@dataclass
class ToolRegistry:
    _tools: dict[str, ToolSpec] = field(default_factory=dict)
    _loaded: bool = False

    def register(
        self,
        *,
        name: str,
        description: str,
        display_name: str | None = None,
        category: str = "general",
        reflection_hint: str | None = None,
        output_kinds: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            spec = ToolSpec(
                name=name,
                description=description,
                display_name=display_name or name.replace("_", " ").title(),
                category=category,
                reflection_hint=reflection_hint,
                func=func,
                output_kinds=output_kinds,
                tags=tags,
            )
            self._tools[name] = spec
            return func

        return decorator

    def load_builtin_tools(self) -> None:
        if self._loaded:
            return

        package_name = "app.tools"
        package = importlib.import_module(package_name)

        # walk_packages recurses into subpackages (e.g. app.tools.rdkit.image),
        # enabling the platform-grouped directory structure:
        #   app/tools/rdkit/    — RDKit agent tools
        #   app/tools/pubchem/  — PubChem lookup tools
        #   app/tools/search/   — web / literature search tools
        #   app/tools/babel/    — Open Babel tools (Phase 2)
        for module_info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            leaf = module_info.name.rsplit(".", 1)[-1]
            if leaf.startswith("_"):
                continue
            importlib.import_module(module_info.name)

        self._loaded = True

    def list_specs(self) -> list[ToolSpec]:
        self.load_builtin_tools()
        return list(self._tools.values())

    def get(self, name: str) -> ToolSpec:
        self.load_builtin_tools()
        return self._tools[name]

    def public_catalog(self) -> list[dict[str, Any]]:
        return [spec.to_public_metadata() for spec in self.list_specs()]


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


tool_registry = ToolRegistry()
tool_result_store = ToolResultStore()

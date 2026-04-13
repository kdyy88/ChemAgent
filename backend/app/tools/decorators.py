from __future__ import annotations

import asyncio
import importlib
import json
import logging
import multiprocessing as mp
import os
import traceback
from functools import wraps
from queue import Empty
from typing import Any, Callable, ParamSpec

from langchain_core.tools import tool
from pydantic import BaseModel

from app.tools.metadata import (
    CHEM_ROUTE_HINT_METADATA_KEY,
    CHEM_TIMEOUT_METADATA_KEY,
    CHEM_TIER_METADATA_KEY,
    ChemToolTier,
)

logger = logging.getLogger(__name__)

P = ParamSpec("P")

DEFAULT_CHEM_TOOL_TIMEOUT_SECONDS = 30.0
_TRACEBACK_LINE_LIMIT = 18
_TRACEBACK_CHAR_LIMIT = 4000
_SYNC_CALLABLE_REGISTRY: dict[str, Callable[..., Any]] = {}


def _translate_protocol(result: Any) -> Any:
    """If *result* is a Chem LSP protocol object, serialise it to annotated
    JSON so that:
    - The LLM sees a clean, human-readable tool result.
    - The executor can detect ``__chem_protocol__`` and route the update
      directly into ``molecule_tree`` / ``viewport`` without touching the
      legacy ``active_smiles`` / ``molecule_workspace`` paths.

    Non-protocol values are returned unchanged (backward compatible).
    """
    # Lazy import avoids circular dependency at module load time.
    from app.agents.contracts.protocol import NodeCreate, NodeUpdate  # noqa: PLC0415

    if isinstance(result, NodeUpdate):
        return json.dumps(
            {
                "__chem_protocol__": "NodeUpdate",
                "artifact_id": result.artifact_id,
                "status": result.status,
                "diagnostics": result.diagnostics,
                "message": f"Molecule {result.artifact_id} diagnostics updated.",
            },
            ensure_ascii=False,
        )
    if isinstance(result, NodeCreate):
        return json.dumps(
            {
                "__chem_protocol__": "NodeCreate",
                "artifact_id": result.artifact_id,
                "smiles": result.smiles,
                "parent_id": result.parent_id,
                "status": result.status,
                "diagnostics": result.diagnostics,
                "message": (
                    f"New molecule {result.artifact_id} created"
                    + (f" from {result.parent_id}." if result.parent_id else ".")
                ),
            },
            ensure_ascii=False,
        )
    return result

class TimeoutException(TimeoutError):
    """Raised when a chemistry tool exceeds its execution time budget."""


class _SubprocessToolError(RuntimeError):
    def __init__(self, error_type: str, details: str, traceback_text: str) -> None:
        super().__init__(details)
        self.error_type = error_type
        self.details = details
        self.traceback_text = traceback_text


def _multiprocessing_context() -> Any:
    methods = mp.get_all_start_methods()
    if os.name == "posix" and "forkserver" in methods:
        return mp.get_context("forkserver")
    return mp.get_context("spawn")


def _format_details(exc: BaseException) -> str:
    details = str(exc).strip()
    return details or repr(exc)


def _clean_traceback(traceback_text: str) -> str:
    lines = [line.rstrip() for line in str(traceback_text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) > _TRACEBACK_LINE_LIMIT:
        lines = ["... traceback trimmed ...", *lines[-_TRACEBACK_LINE_LIMIT:]]
    cleaned = "\n".join(lines)
    if len(cleaned) > _TRACEBACK_CHAR_LIMIT:
        cleaned = "... traceback trimmed ...\n" + cleaned[-_TRACEBACK_CHAR_LIMIT:]
    return cleaned


def _suggest_recovery(error_type: str, details: str) -> str:
    lowered = f"{error_type} {details}".lower()
    if "timeout" in lowered:
        return "Simplify the molecule, reduce optimisation steps, or adjust the execution parameters before retrying."
    if any(keyword in lowered for keyword in ("smiles", "valence", "sanitize", "kekulize", "aromatic", "parse")):
        return "Please review the chemical validity of the input SMILES or adjust the execution parameters and try again."
    return "Inspect the traceback, correct the tool arguments or workflow assumptions, and retry the computation."


def _build_error_payload(
    *,
    tool_name: str,
    error_type: str,
    details: str,
    traceback_text: str,
    timeout_seconds: float,
) -> str:
    cleaned_traceback = _clean_traceback(traceback_text)
    suggestion = _suggest_recovery(error_type, details)
    formatted_error = "\n".join(
        [
            "[Execution Failed]",
            f"Tool: {tool_name}",
            f"Error Type: {error_type}",
            f"Details: {details}",
            *( [f"Traceback: {cleaned_traceback}"] if cleaned_traceback else [] ),
            f"Suggestion for Agent: {suggestion}",
        ]
    )
    return json.dumps(
        {
            "status": "error",
            "error_boundary": "safe_chem_tool",
            "tool_name": tool_name,
            "error": formatted_error,
            "error_type": error_type,
            "details": details,
            "traceback": cleaned_traceback,
            "suggestion": suggestion,
            "timeout_seconds": timeout_seconds,
            "is_retryable": True,
        },
        ensure_ascii=False,
        indent=2,
    )


def _subprocess_entry(
    registry_key: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    queue: Any,
) -> None:
    try:
        func = _resolve_registered_callable(registry_key)
        queue.put(("ok", func(*args, **kwargs)))
    except Exception as exc:  # noqa: BLE001
        queue.put(
            (
                "error",
                {
                    "error_type": type(exc).__name__,
                    "details": _format_details(exc),
                    "traceback": traceback.format_exc(),
                },
            )
        )


def _resolve_registered_callable(registry_key: str) -> Callable[..., Any]:
    module_name, _, qualname = registry_key.partition(":")
    if "<locals>" in qualname:
        raise ValueError(f"safe_chem_tool requires top-level callables for sync timeout execution: {registry_key}")

    importlib.import_module(module_name)
    current = _SYNC_CALLABLE_REGISTRY.get(registry_key)
    if current is None:
        raise LookupError(f"safe_chem_tool registry miss for {registry_key}")
    return current


def _run_sync_with_timeout(
    func: Callable[P, Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    timeout_seconds: float,
) -> Any:
    ctx = _multiprocessing_context()
    queue = ctx.Queue(maxsize=1)
    registry_key = f"{func.__module__}:{func.__qualname__}"
    process = ctx.Process(
        target=_subprocess_entry,
        args=(registry_key, args, kwargs, queue),
    )
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(1)
        raise TimeoutException(f"Execution exceeded {timeout_seconds:g}s timeout.")

    try:
        status, payload = queue.get_nowait()
    except Empty:
        if process.exitcode not in (0, None):
            raise RuntimeError(f"Chemistry subprocess exited unexpectedly with code {process.exitcode}.")
        raise RuntimeError("Chemistry subprocess completed without returning a result.")
    finally:
        queue.close()
        queue.join_thread()

    if status == "ok":
        return payload

    raise _SubprocessToolError(
        str(payload.get("error_type") or "RuntimeError"),
        str(payload.get("details") or "Chemistry subprocess failed."),
        str(payload.get("traceback") or ""),
    )


def safe_chem_tool(timeout: float = DEFAULT_CHEM_TOOL_TIMEOUT_SECONDS) -> Callable[[Callable[P, Any]], Callable[P, Any]]:
    """Wrap chemistry tools with timeout control and structured failure payloads."""

    timeout_seconds = max(float(timeout), 0.1)

    def decorator(func: Callable[P, Any]) -> Callable[P, Any]:
        tool_name = func.__name__
        _SYNC_CALLABLE_REGISTRY[f"{func.__module__}:{func.__qualname__}"] = func

        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                try:
                    return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_seconds)
                except asyncio.TimeoutError:
                    logger.warning("Chem tool timed out: %s (timeout=%ss)", tool_name, timeout_seconds)
                    return _build_error_payload(
                        tool_name=tool_name,
                        error_type="TimeoutException",
                        details=f"Execution exceeded {timeout_seconds:g}s timeout.",
                        traceback_text=f"TimeoutException: Execution exceeded {timeout_seconds:g}s timeout.",
                        timeout_seconds=timeout_seconds,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Chem tool failed: %s", tool_name, exc_info=True)
                    return _build_error_payload(
                        tool_name=tool_name,
                        error_type=type(exc).__name__,
                        details=_format_details(exc),
                        traceback_text=traceback.format_exc(),
                        timeout_seconds=timeout_seconds,
                    )

            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            try:
                return _run_sync_with_timeout(func, args, kwargs, timeout_seconds=timeout_seconds)
            except TimeoutException:
                logger.warning("Chem tool timed out: %s (timeout=%ss)", tool_name, timeout_seconds)
                return _build_error_payload(
                    tool_name=tool_name,
                    error_type="TimeoutException",
                    details=f"Execution exceeded {timeout_seconds:g}s timeout.",
                    traceback_text=f"TimeoutException: Execution exceeded {timeout_seconds:g}s timeout.",
                    timeout_seconds=timeout_seconds,
                )
            except _SubprocessToolError as exc:
                logger.warning("Chem tool failed in subprocess: %s", tool_name)
                return _build_error_payload(
                    tool_name=tool_name,
                    error_type=exc.error_type,
                    details=exc.details,
                    traceback_text=exc.traceback_text,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Chem tool failed: %s", tool_name, exc_info=True)
                return _build_error_payload(
                    tool_name=tool_name,
                    error_type=type(exc).__name__,
                    details=_format_details(exc),
                    traceback_text=traceback.format_exc(),
                    timeout_seconds=timeout_seconds,
                )

        return sync_wrapper

    return decorator


def chem_tool(
    *,
    tier: ChemToolTier,
    timeout: float = DEFAULT_CHEM_TOOL_TIMEOUT_SECONDS,
    args_schema: type[BaseModel] | None = None,
    metadata: dict[str, Any] | None = None,
    route_hint: str | None = None,
) -> Callable[[Callable[P, Any]], Any]:
    """Register a chemistry tool with unified safety and tier metadata.

    This keeps LangChain registration, timeout/error boundaries, and tool tier
    metadata co-located so tool classification can be derived from the tool
    object instead of scattered decorator stacks and side tables.
    """

    merged_metadata = dict(metadata or {})
    merged_metadata[CHEM_TIER_METADATA_KEY] = tier
    merged_metadata[CHEM_TIMEOUT_METADATA_KEY] = max(float(timeout), 0.1)
    if route_hint:
        merged_metadata[CHEM_ROUTE_HINT_METADATA_KEY] = route_hint

    def decorator(func: Callable[P, Any]) -> Any:
        safe_callable = safe_chem_tool(timeout=timeout)(func)
        tool_kwargs: dict[str, Any] = {}
        if args_schema is not None:
            tool_kwargs["args_schema"] = args_schema

        # Protocol translator wrapper: converts NodeUpdate / NodeCreate to
        # annotated JSON; all other return values pass through unchanged.
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def state_diff_wrapper(*args: Any, **kwargs: Any) -> Any:
                return _translate_protocol(await safe_callable(*args, **kwargs))
        else:
            @wraps(func)
            def state_diff_wrapper(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
                return _translate_protocol(safe_callable(*args, **kwargs))

        registered_tool = tool(**tool_kwargs)(state_diff_wrapper)
        existing_metadata = getattr(registered_tool, "metadata", None) or {}
        registered_tool.metadata = {**existing_metadata, **merged_metadata}
        return registered_tool

    return decorator
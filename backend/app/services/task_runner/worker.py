"""
task_runner/worker — ARQ worker entry point.

Canonical location.  The top-level app/worker.py re-exports WorkerSettings for
backward compatibility with `arq app.worker.WorkerSettings`.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from app.core.redis_pool import (
    build_redis_settings,
    get_default_artifact_ttl_seconds,
    get_default_result_ttl_seconds,
    get_worker_job_timeout_seconds,
    get_worker_max_jobs,
)
from app.domain.store.artifact_store import store_artifact, store_task_result
from app.services.task_runner.registry import TASK_DISPATCH, TaskFn

_TASK_DISPATCH = TASK_DISPATCH  # local alias so rest of file is unchanged

# ── Parameter bounds enforced before handing kwargs to chemistry functions ────
_STEPS_MAX = 5_000
_PH_MIN, _PH_MAX = 0.0, 14.0
_STRING_MAX_LEN = 100_000  # ~100 KB; catches accidental large SDF payloads


def _validate_task_kwargs(task_name: str, kwargs: dict[str, Any]) -> str | None:
    """Return an error string if any parameter is out of bounds, else None."""
    steps = kwargs.get("steps")
    if steps is not None:
        try:
            s = int(steps)
        except (TypeError, ValueError):
            return f"'steps' must be an integer, got {type(steps).__name__}"
        if s < 1 or s > _STEPS_MAX:
            return f"'steps' must be between 1 and {_STEPS_MAX}, got {s}"

    ph = kwargs.get("ph")
    if ph is not None:
        try:
            p = float(ph)
        except (TypeError, ValueError):
            return f"'ph' must be a number, got {type(ph).__name__}"
        if not (_PH_MIN <= p <= _PH_MAX):
            return f"'ph' must be between {_PH_MIN} and {_PH_MAX}, got {p}"

    for key, val in kwargs.items():
        if isinstance(val, str) and len(val) > _STRING_MAX_LEN:
            return f"'{key}' exceeds maximum allowed length of {_STRING_MAX_LEN} characters"

    return None


def _sanitize_stem(name: str | None, fallback: str) -> str:
    stem = (name or "").strip()
    if stem.lower().endswith(".sdf"):
        stem = stem[:-4]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return stem or fallback


async def _execute_task(task_name: str, kwargs: dict[str, Any], task_id: str) -> dict[str, Any]:
    fn: TaskFn | None = _TASK_DISPATCH.get(task_name)
    if fn is None:
        return {"is_valid": False, "error": f"未知任务：{task_name}"}

    task_kwargs = dict(kwargs)
    filename_base = task_kwargs.pop("filename_base", None)

    validation_error = _validate_task_kwargs(task_name, task_kwargs)
    if validation_error:
        return {"is_valid": False, "error": f"参数校验失败：{validation_error}"}

    result = await asyncio.to_thread(fn, **task_kwargs)

    if task_name == "babel.sdf_split" and result.get("is_valid"):
        zip_bytes = result.pop("zip_bytes", b"")
        download_id = task_id
        filename_stem = _sanitize_stem(filename_base, "split")
        await store_artifact(
            download_id,
            content=zip_bytes,
            filename=f"{filename_stem}_split.zip",
            media_type="application/zip",
            ttl_seconds=get_default_artifact_ttl_seconds(),
        )
        result["download_id"] = download_id

    if task_name == "babel.sdf_merge" and result.get("is_valid"):
        sdf_content = result.pop("sdf_content", "")
        download_id = task_id
        filename_stem = _sanitize_stem(filename_base, "merged_library")
        await store_artifact(
            download_id,
            content=sdf_content.encode("utf-8"),
            filename=f"{filename_stem}.sdf",
            media_type="chemical/x-mdl-sdfile",
            ttl_seconds=get_default_artifact_ttl_seconds(),
        )
        result["download_id"] = download_id

    return result


async def run_chem_task(ctx: dict[str, Any], task_name: str, kwargs: dict[str, Any], task_id: str) -> dict[str, Any]:
    try:
        result = await _execute_task(task_name, kwargs, task_id)
    except Exception as exc:
        result = {"is_valid": False, "error": f"任务执行失败：{exc}"}

    await store_task_result(task_id, result, ttl_seconds=get_default_result_ttl_seconds())
    return result


class WorkerSettings:
    functions = [run_chem_task]
    redis_settings = build_redis_settings()
    max_jobs = get_worker_max_jobs()
    job_timeout = get_worker_job_timeout_seconds()
    queue_name = "arq:queue"

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from app.core.task_queue import (
    build_redis_settings,
    get_default_artifact_ttl_seconds,
    get_default_result_ttl_seconds,
    get_worker_job_timeout_seconds,
    get_worker_max_jobs,
    store_artifact,
    store_task_result,
)

from app.core.task_registry import TASK_DISPATCH, TaskFn

_TASK_DISPATCH = TASK_DISPATCH  # keep the local alias so rest of file is unchanged


def _sanitize_stem(name: str | None, fallback: str) -> str:
    stem = (name or "").strip()
    if stem.lower().endswith(".sdf"):
        stem = stem[:-4]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return stem or fallback


async def _execute_task(task_name: str, kwargs: dict[str, Any], task_id: str) -> dict[str, Any]:
    fn = _TASK_DISPATCH.get(task_name)
    if fn is None:
        return {"is_valid": False, "error": f"未知任务：{task_name}"}

    task_kwargs = dict(kwargs)
    filename_base = task_kwargs.pop("filename_base", None)
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
    keep_result = 0
    queue_name = os.environ.get("CHEMAGENT_QUEUE_NAME", "arq:queue")

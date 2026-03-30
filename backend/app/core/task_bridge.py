from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from app.core.task_queue import (
    delete_task_result,
    get_arq_pool,
    get_poll_interval_seconds,
    read_task_result,
)
from app.core.task_registry import TASK_DISPATCH

log = logging.getLogger(__name__)


async def _run_direct(task_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Execute a chem task in-process (thread pool) without Redis.

    Used as a fallback when Redis/ARQ is unavailable (local dev, CI).
    Strips `filename_base` since that only affects ARQ artifact storage.
    """
    fn = TASK_DISPATCH.get(task_name)
    if fn is None:
        return {"is_valid": False, "error": f"未知任务：{task_name}"}
    kw = {k: v for k, v in kwargs.items() if k != "filename_base"}
    return await asyncio.to_thread(fn, **kw)


async def run_via_worker(
    task_name: str,
    kwargs: dict[str, Any],
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    task_id = f"task_{uuid4().hex}"

    # ── Try Redis/ARQ path ───────────────────────────────────────────────────
    try:
        arq_pool = await get_arq_pool()
        await arq_pool.enqueue_job("run_chem_task", task_name, kwargs, task_id, _job_id=task_id)
    except Exception as exc:
        # Redis unavailable (local dev without Docker) — fall back to direct
        # in-process execution so all endpoints still work.
        log.debug("Redis unavailable (%s) — running %s directly", exc, task_name)
        return await _run_direct(task_name, kwargs)

    # ── Poll Redis for result ────────────────────────────────────────────────
    poll_interval = get_poll_interval_seconds()

    try:
        async with asyncio.timeout(timeout):
            while True:
                result = await read_task_result(task_id)
                if result is not None:
                    await delete_task_result(task_id)
                    return result
                await asyncio.sleep(poll_interval)
    except TimeoutError:
        # ARQ worker is not consuming jobs (worker not started in local dev).
        # Fall back to direct in-process execution so the endpoint still works.
        log.debug("ARQ worker not responding after %.1fs — running %s directly", timeout, task_name)
        return await _run_direct(task_name, kwargs)

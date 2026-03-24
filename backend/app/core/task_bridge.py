from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from app.core.task_queue import (
    delete_task_result,
    get_arq_pool,
    get_poll_interval_seconds,
    read_task_result,
)


async def run_via_worker(
    task_name: str,
    kwargs: dict[str, Any],
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    task_id = f"task_{uuid4().hex}"

    try:
        arq_pool = await get_arq_pool()
        await arq_pool.enqueue_job("run_chem_task", task_name, kwargs, task_id, _job_id=task_id)
    except Exception as exc:
        return {
            "is_valid": False,
            "error": f"任务入队失败：{exc}",
        }

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
        return {
            "is_valid": False,
            "error": "计算超时，请稍后重试。",
        }

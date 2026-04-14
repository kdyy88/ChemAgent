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
from app.services.task_runner.registry import TASK_DISPATCH

log = logging.getLogger(__name__)


def _build_task_envelope(
    task_id: str,
    task_name: str,
    result: dict[str, Any] | None,
    *,
    task_context: dict[str, Any] | None = None,
    delivery: str,
    status: str | None = None,
    fallback_reason: str = "",
) -> dict[str, Any]:
    normalized_result = dict(result or {})
    return {
        "task_id": task_id,
        "task_name": task_name,
        "status": status or ("completed" if normalized_result.get("is_valid", True) else "failed"),
        "result": normalized_result,
        "task_context": dict(task_context or {}),
        "delivery": delivery,
        "fallback_reason": fallback_reason,
    }


def _normalize_task_envelope(
    payload: dict[str, Any],
    *,
    task_id: str,
    task_name: str,
    task_context: dict[str, Any] | None,
    delivery: str,
) -> dict[str, Any]:
    if isinstance(payload.get("result"), dict) and payload.get("task_id"):
        envelope = dict(payload)
        envelope.setdefault("task_name", task_name)
        envelope.setdefault("task_context", dict(task_context or {}))
        envelope.setdefault("delivery", delivery)
        envelope.setdefault("fallback_reason", "")
        envelope.setdefault(
            "status",
            "completed" if envelope["result"].get("is_valid", True) else "failed",
        )
        return envelope
    return _build_task_envelope(
        task_id,
        task_name,
        payload,
        task_context=task_context,
        delivery=delivery,
    )


async def _run_direct(task_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Execute a chem task in-process (thread pool) without Redis.

    Used as a fallback when Redis/ARQ is unavailable (local dev, CI).
    Strips `filename_base` since that only affects ARQ artifact storage.
    """
    spec = TASK_DISPATCH.get(task_name)
    if spec is None:
        return {"is_valid": False, "error": f"未知任务：{task_name}"}
    kw = {k: v for k, v in kwargs.items() if k != "filename_base"}
    return await asyncio.to_thread(spec.fn, **kw)


async def submit_task_to_worker(
    task_name: str,
    kwargs: dict[str, Any],
    *,
    task_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_id = f"task_{uuid4().hex}"

    try:
        arq_pool = await get_arq_pool()
        await arq_pool.enqueue_job(
            "run_chem_task",
            task_name,
            kwargs,
            task_id,
            dict(task_context or {}),
            _job_id=task_id,
        )
        return _build_task_envelope(
            task_id,
            task_name,
            None,
            task_context=task_context,
            delivery="worker",
            status="queued",
        )
    except Exception as exc:
        log.debug("Redis unavailable (%s) — running %s directly", exc, task_name)
        direct_result = await _run_direct(task_name, kwargs)
        return _build_task_envelope(
            task_id,
            task_name,
            direct_result,
            task_context=task_context,
            delivery="direct",
            fallback_reason=str(exc),
        )


async def poll_task_result(
    task_id: str,
    *,
    task_name: str = "",
    task_context: dict[str, Any] | None = None,
    delete_after_read: bool = True,
) -> dict[str, Any] | None:
    result = await read_task_result(task_id)
    if result is None:
        return None
    if delete_after_read:
        await delete_task_result(task_id)
    return _normalize_task_envelope(
        result,
        task_id=task_id,
        task_name=task_name,
        task_context=task_context,
        delivery="worker",
    )


async def wait_for_task_result(
    task_id: str,
    *,
    task_name: str = "",
    kwargs: dict[str, Any] | None = None,
    task_context: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    poll_interval = get_poll_interval_seconds()

    try:
        async with asyncio.timeout(timeout):
            while True:
                envelope = await poll_task_result(
                    task_id,
                    task_name=task_name,
                    task_context=task_context,
                )
                if envelope is not None:
                    return envelope
                await asyncio.sleep(poll_interval)
    except TimeoutError:
        try:
            arq_pool = await get_arq_pool()
            await arq_pool.abort_job(task_id)
        except Exception as abort_exc:
            log.debug("Could not abort ARQ job %s: %s", task_id, abort_exc)

        log.debug("ARQ worker not responding after %.1fs — running %s directly", timeout, task_name)
        direct_result = await _run_direct(task_name, dict(kwargs or {}))
        return _build_task_envelope(
            task_id,
            task_name,
            direct_result,
            task_context=task_context,
            delivery="direct",
            fallback_reason="timeout",
        )


async def run_via_worker(
    task_name: str,
    kwargs: dict[str, Any],
    *,
    timeout: float = 5.0,
    task_context: dict[str, Any] | None = None,
    return_envelope: bool = False,
) -> dict[str, Any]:
    submission = await submit_task_to_worker(
        task_name,
        kwargs,
        task_context=task_context,
    )
    if submission["status"] != "queued":
        return submission if return_envelope else submission["result"]

    envelope = await wait_for_task_result(
        submission["task_id"],
        task_name=task_name,
        kwargs=kwargs,
        task_context=task_context,
        timeout=timeout,
    )
    return envelope if return_envelope else envelope["result"]

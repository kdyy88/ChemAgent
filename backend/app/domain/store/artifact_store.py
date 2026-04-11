"""
Artifact store — Redis-backed CRUD for task results and binary artifacts.

Extracted from core/task_queue.py.  core/task_queue.py re-exports for backward
compatibility.
"""
from __future__ import annotations

import json
from typing import Any

from app.core.redis_pool import (
    artifact_data_key,
    artifact_meta_key,
    get_default_artifact_ttl_seconds,
    get_default_result_ttl_seconds,
    get_redis_pool,
    task_result_key,
)


async def store_task_result(task_id: str, payload: dict[str, Any], ttl_seconds: int | None = None) -> None:
    redis = await get_redis_pool()
    ttl = ttl_seconds or get_default_result_ttl_seconds()
    await redis.set(task_result_key(task_id), json.dumps(payload, ensure_ascii=False), ex=ttl)


async def read_task_result(task_id: str) -> dict[str, Any] | None:
    redis = await get_redis_pool()
    raw = await redis.get(task_result_key(task_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


async def delete_task_result(task_id: str) -> None:
    redis = await get_redis_pool()
    await redis.delete(task_result_key(task_id))


async def store_artifact(
    result_id: str,
    *,
    content: bytes,
    filename: str,
    media_type: str,
    ttl_seconds: int | None = None,
) -> None:
    redis = await get_redis_pool()
    ttl = ttl_seconds or get_default_artifact_ttl_seconds()
    await redis.set(artifact_data_key(result_id), content, ex=ttl)
    await redis.set(
        artifact_meta_key(result_id),
        json.dumps({"filename": filename, "media_type": media_type}, ensure_ascii=False),
        ex=ttl,
    )


async def read_artifact(result_id: str) -> tuple[bytes, dict[str, str]] | None:
    redis = await get_redis_pool()
    data, raw_meta = await redis.mget(artifact_data_key(result_id), artifact_meta_key(result_id))
    if data is None or raw_meta is None:
        return None
    if isinstance(raw_meta, bytes):
        raw_meta = raw_meta.decode("utf-8")
    meta = json.loads(raw_meta)
    return data, meta

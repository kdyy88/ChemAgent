from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from dotenv import load_dotenv
from redis.asyncio import Redis

# Use localhost for local dev. Docker Compose sets REDIS_URL=redis://redis:6379/0 via env.
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_TASK_RESULT_PREFIX = "chemagent:task-result:"
_ARTIFACT_DATA_PREFIX = "chemagent:artifact:data:"
_ARTIFACT_META_PREFIX = "chemagent:artifact:meta:"
_DEFAULT_RESULT_TTL_SECONDS = 300
_DEFAULT_ARTIFACT_TTL_SECONDS = 300

_arq_pool: ArqRedis | None = None
_redis_pool: Redis | None = None
_arq_pool_lock = asyncio.Lock()
_redis_pool_lock = asyncio.Lock()

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env", override=False)


def get_redis_url() -> str:
    return os.environ.get("REDIS_URL", _DEFAULT_REDIS_URL).strip() or _DEFAULT_REDIS_URL


def get_default_result_ttl_seconds() -> int:
    return int(os.environ.get("TASK_RESULT_TTL_SECONDS", str(_DEFAULT_RESULT_TTL_SECONDS)))


def get_default_artifact_ttl_seconds() -> int:
    return int(os.environ.get("ARTIFACT_TTL_SECONDS", str(_DEFAULT_ARTIFACT_TTL_SECONDS)))


def get_worker_max_jobs() -> int:
    return int(os.environ.get("CHEMAGENT_WORKER_MAX_JOBS", "2"))


def get_worker_job_timeout_seconds() -> int:
    return int(os.environ.get("CHEMAGENT_WORKER_JOB_TIMEOUT_SECONDS", "120"))


def get_poll_interval_seconds() -> float:
    return float(os.environ.get("TASK_POLL_INTERVAL_SECONDS", "0.2"))


def build_redis_settings() -> RedisSettings:
    settings = RedisSettings.from_dsn(get_redis_url())
    # Fail fast so the direct-execution fallback in task_bridge kicks in
    # within ~100 ms instead of waiting 5+ seconds for retries.
    settings.conn_retries = 1
    settings.conn_retry_delay = 0.05
    return settings


async def get_arq_pool() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        async with _arq_pool_lock:
            if _arq_pool is None:
                _arq_pool = await create_pool(build_redis_settings())
    return _arq_pool


async def get_redis_pool() -> Redis:
    global _redis_pool
    if _redis_pool is None:
        async with _redis_pool_lock:
            if _redis_pool is None:
                _redis_pool = Redis.from_url(get_redis_url())
    return _redis_pool


def task_result_key(task_id: str) -> str:
    return f"{_TASK_RESULT_PREFIX}{task_id}"


def artifact_data_key(result_id: str) -> str:
    return f"{_ARTIFACT_DATA_PREFIX}{result_id}"


def artifact_meta_key(result_id: str) -> str:
    return f"{_ARTIFACT_META_PREFIX}{result_id}"


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

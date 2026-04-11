from __future__ import annotations

import asyncio
import os

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.asyncio import Redis

_DEFAULT_REDIS_URL = "redis://localhost:6379/0"

_arq_pool: ArqRedis | None = None
_redis_pool: Redis | None = None
_arq_pool_lock = asyncio.Lock()
_redis_pool_lock = asyncio.Lock()


def get_redis_url() -> str:
    return os.environ.get("REDIS_URL", _DEFAULT_REDIS_URL).strip() or _DEFAULT_REDIS_URL


def build_redis_settings() -> RedisSettings:
    settings = RedisSettings.from_dsn(get_redis_url())
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
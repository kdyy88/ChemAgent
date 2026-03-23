"""
Redis connection management.

Two clients are exported:
- ``get_redis()``           — async Redis (for WebSocket handlers, session state, rate limiting)
- ``get_sync_redis()``      — sync  Redis (for tool execution callbacks running in threads)

Both share the same REDIS_URL env-var but use independent connection pools so
there is no cross-event-loop or thread-safety issue.

Pool sizing rationale (max_connections=100):
  50 concurrent WS connections × ~2 parallel Redis ops each = 100.
  Redis connections are extremely lightweight (~50 KB/conn), so 100 connections
  cost < 5 MB while fully eliminating client-side queuing under peak load.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

import redis
import redis.asyncio as aioredis

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


# ── Typed async Redis Protocol ────────────────────────────────────────────────
# redis-py 5.x types async-client methods as Union[Awaitable[T], T] because
# the same method body is shared with the sync client.  Pylance cannot narrow
# the Union, so ``await redis.hset(...)`` raises a type error.
# Defining an AsyncRedis Protocol with proper ``async def`` signatures fixes
# the issue at the call-site without suppressing any diagnostics.

@runtime_checkable
class AsyncRedis(Protocol):
    """Structural protocol for the subset of redis.asyncio.Redis used in this app."""

    async def ping(self) -> bool: ...
    async def exists(self, *names: str) -> int: ...
    async def expire(self, name: str, time: int) -> bool: ...
    async def delete(self, *names: str) -> int: ...
    async def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        mapping: dict[str, Any] | None = None,
        items: list[Any] | None = None,
    ) -> int: ...
    async def hgetall(self, name: str) -> dict[str, str]: ...
    async def lrange(self, name: str, start: int, end: int) -> list[str]: ...
    async def rpush(self, name: str, *values: str) -> int: ...
    async def ltrim(self, name: str, start: int, end: int) -> bool: ...
    async def aclose(self) -> None: ...


# ── Async client (for FastAPI / asyncio context) ──────────────────────────────

_async_pool: aioredis.ConnectionPool | None = None
_async_client: aioredis.Redis | None = None


def _make_async_pool() -> aioredis.ConnectionPool:
    return aioredis.ConnectionPool.from_url(
        _REDIS_URL,
        max_connections=100,
        decode_responses=True,
    )


def get_redis() -> AsyncRedis:
    """Return the shared async Redis client. Call after ``init_redis()``.

    Return type is ``AsyncRedis`` (a Protocol) so callers get proper awaitable
    method signatures.  At runtime this is always an ``aioredis.Redis`` instance.
    """
    global _async_client
    if _async_client is None:
        raise RuntimeError("Redis not initialised — call init_redis() first")
    return _async_client  # type: ignore[return-value]  # aioredis.Redis satisfies AsyncRedis at runtime


async def init_redis() -> None:
    """Initialise the async Redis pool and verify connectivity."""
    global _async_pool, _async_client
    _async_pool = _make_async_pool()
    _async_client = aioredis.Redis(connection_pool=_async_pool)
    await _async_client.ping()


async def close_redis() -> None:
    """Gracefully close the async Redis pool."""
    global _async_client, _async_pool
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None
    if _async_pool is not None:
        await _async_pool.aclose()
        _async_pool = None


# ── Sync client (for tool execution callbacks running in IO_POOL threads) ─────
#
# Tool callbacks run in ThreadPoolExecutor threads where there is no running
# event loop.  Using the async client from a thread would require
# asyncio.run() which would start a NEW event loop — fine in a thread —
# but it's simpler and more performant to use the dedicated sync client.

_sync_client: redis.Redis | None = None


def get_sync_redis() -> redis.Redis:
    """Return the shared synchronous Redis client (thread-safe, lazy init)."""
    global _sync_client
    if _sync_client is None:
        _sync_client = redis.Redis.from_url(
            _REDIS_URL,
            max_connections=50,
            decode_responses=True,
        )
    return _sync_client

"""Engine-level artifact store — data-plane persistence for ChemSessionEngine.

Stores arbitrary JSON-serializable values (SDF text, PDBQT content,
large descriptor matrices, etc.) that are too large to embed in SSE frames
or LLM context windows.

Persistence strategy
────────────────────
1. **Redis (primary)** — uses the shared pool from ``task_queue``; per-key TTL
   defaults to 1 hour.  Artifacts survive the owning HTTP request and can be
   retrieved by ``GET /api/chat/artifacts/{artifact_id}``.
2. **In-process fallback** — when Redis is unreachable the value is stashed in a
   module-level dict so the request still completes; these entries vanish when
   the process restarts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.task_queue import get_redis_pool

logger = logging.getLogger(__name__)

_ENGINE_ARTIFACT_PREFIX = "chemagent:engine-artifact:"
_DEFAULT_TTL_SECONDS = 3600  # 1 hour

# In-process fallback — used when Redis is unavailable.
# Capped at 256 entries (FIFO eviction) to prevent unbounded growth during
# prolonged Redis outages.
_local_fallback: dict[str, str] = {}
_LOCAL_FALLBACK_MAX = 256


def _artifact_key(artifact_id: str) -> str:
    return f"{_ENGINE_ARTIFACT_PREFIX}{artifact_id}"


async def store_engine_artifact(
    artifact_id: str,
    data: Any,
    *,
    ttl: int = _DEFAULT_TTL_SECONDS,
) -> None:
    """Serialize ``data`` and persist it under ``artifact_id``.

    Falls back to an in-process dict when Redis is unreachable so that
    callers never have to handle a storage error at the SSE level.
    """
    serialized = json.dumps(data, ensure_ascii=False)
    try:
        redis = await get_redis_pool()
        await redis.set(_artifact_key(artifact_id), serialized, ex=ttl)
        logger.debug("Stored engine artifact %s in Redis (ttl=%ss)", artifact_id, ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Redis unavailable — falling back to in-process artifact store: %s", exc
        )
        _local_fallback[artifact_id] = serialized
        # FIFO eviction: drop oldest entry when cap is exceeded
        if len(_local_fallback) > _LOCAL_FALLBACK_MAX:
            oldest = next(iter(_local_fallback))
            del _local_fallback[oldest]


async def get_engine_artifact(artifact_id: str) -> Any | None:
    """Retrieve an engine artifact by ID.

    Checks Redis first; falls back to the in-process dict.
    Returns ``None`` when the artifact is not found or has expired.
    """
    try:
        redis = await get_redis_pool()
        raw = await redis.get(_artifact_key(artifact_id))
        if raw is not None:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable — checking in-process fallback: %s", exc)

    serialized = _local_fallback.get(artifact_id)
    if serialized is not None:
        return json.loads(serialized)

    return None

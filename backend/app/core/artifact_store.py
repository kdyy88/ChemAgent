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
import os
from typing import Any

from app.core.task_queue import get_redis_pool

logger = logging.getLogger(__name__)

_ENGINE_ARTIFACT_PREFIX = "chemagent:engine-artifact:"
# Read from ARTIFACT_TTL_SECONDS env var (default 86400s = 24h for HITL flows)
# Local dev can override via .env or compose.yaml
_DEFAULT_TTL_SECONDS = int(os.getenv("ARTIFACT_TTL_SECONDS", "86400"))
_EXPIRY_WARNING_SECONDS = int(os.getenv("ARTIFACT_EXPIRY_WARNING_SECONDS", "1800"))

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


async def get_engine_artifact_warning(artifact_id: str) -> str | None:
    """Return a human-readable warning when an artifact is missing or near expiry."""
    if not artifact_id:
        return None

    key = _artifact_key(artifact_id)
    try:
        redis = await get_redis_pool()
        exists = await redis.exists(key)
        if not exists:
            return f"[Warning: Artifact {artifact_id} is unavailable or has expired.]"

        remaining_ttl = await redis.ttl(key)
        if 0 < remaining_ttl <= _EXPIRY_WARNING_SECONDS:
            return (
                f"[Warning: Artifact {artifact_id} is nearing expiration "
                f"({remaining_ttl}s remaining). Prioritize using or refreshing it.]"
            )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable — unable to inspect artifact TTL for %s: %s", artifact_id, exc)

    if artifact_id in _local_fallback:
        return None
    return f"[Warning: Artifact {artifact_id} is unavailable or has expired.]"


async def patch_engine_artifact(
    artifact_id: str,
    patch: dict[str, Any],
) -> bool:
    """Merge-patch an existing artifact with new top-level keys.

    Performs a **shallow** merge: ``existing.update(patch)``.  Existing keys
    not present in *patch* are left untouched.  The write inherits the
    artifact's remaining Redis TTL so the expiry clock is never reset.

    This function is intended for **passive metadata attachment only**
    (bioactivity, synthesizability, async enrichment scores, etc.).  Core
    molecular topology fields such as ``canonical_smiles`` should not be
    mutated in-place; chemistry state transitions must create a new immutable
    artifact record with ``parent_artifact_id`` lineage.

    Parameters
    ----------
    artifact_id:
        ID of the artifact to update.
    patch:
        Dict of top-level keys to add or overwrite.  Arbitrary keys are
        accepted, enabling downstream modules (bioactivity, synthesizability,
        etc.) to attach data without modifying the writer's schema.

    Returns
    -------
    bool
        ``True`` on success, ``False`` if the artifact does not exist.

    Raises
    ------
    Nothing — all exceptions are caught and logged as warnings.
    """
    existing = await get_engine_artifact(artifact_id)
    if existing is None:
        logger.warning("patch_engine_artifact: artifact %s not found — patch skipped", artifact_id)
        return False

    existing.update(patch)
    serialized = json.dumps(existing, ensure_ascii=False)

    # Try to inherit the remaining Redis TTL so the expiry clock is unchanged.
    try:
        redis = await get_redis_pool()
        key = _artifact_key(artifact_id)
        remaining_ttl = await redis.ttl(key)
        # ttl() returns -1 (no expiry) or -2 (key missing); treat both as
        # "use default" so we don't silently make entries immortal.
        ttl = remaining_ttl if remaining_ttl > 0 else _DEFAULT_TTL_SECONDS
        await redis.set(key, serialized, ex=ttl)
        logger.debug("Patched engine artifact %s in Redis (remaining_ttl=%ss)", artifact_id, ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable — patching in-process fallback: %s", exc)
        _local_fallback[artifact_id] = serialized

    return True

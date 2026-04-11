"""Engine-level artifact store — data-plane persistence for ChemSessionEngine.

Stores arbitrary JSON-serializable values (SDF text, PDBQT content,
large descriptor matrices, etc.) that are too large to embed in SSE frames
or LLM context windows.

Persistence strategy
────────────────────
1. **Redis (primary)** — uses the shared pool from ``task_queue``; per-key TTL
    defaults to 1 hour.  Artifacts survive the owning HTTP request and can be
    retrieved by ``GET /api/v1/chat/artifacts/{artifact_id}``.
2. **In-process fallback** — when Redis is unreachable the value is stashed in a
   module-level dict so the request still completes; these entries vanish when
   the process restarts.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.core.task_queue import get_redis_pool

logger = logging.getLogger(__name__)

_ENGINE_ARTIFACT_PREFIX = "chemagent:engine-artifact:"
_TEMP_ARTIFACT_TTL_SECONDS = int(os.getenv("ARTIFACT_TEMP_TTL_SECONDS", os.getenv("ARTIFACT_TTL_SECONDS", "3600")))
_EXPIRY_WARNING_SECONDS = int(os.getenv("ARTIFACT_EXPIRY_WARNING_SECONDS", "1800"))
_ARTIFACT_ENVELOPE_VERSION = 1

# In-process fallback — used when Redis is unavailable.
# Capped at 256 entries (FIFO eviction) to prevent unbounded growth during
# prolonged Redis outages.
_local_fallback: dict[str, str] = {}
_LOCAL_FALLBACK_MAX = 256


def _artifact_key(artifact_id: str) -> str:
    return f"{_ENGINE_ARTIFACT_PREFIX}{artifact_id}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_artifact_envelope(
    artifact_id: str,
    data: Any,
    *,
    tier: str,
    ttl: int | None,
    created_at: str | None = None,
    promoted_at: str | None = None,
) -> dict[str, Any]:
    timestamp = created_at or _utc_now_iso()
    meta: dict[str, Any] = {
        "artifact_id": artifact_id,
        "tier": tier,
        "created_at": timestamp,
        "storage_version": _ARTIFACT_ENVELOPE_VERSION,
    }
    if ttl is not None and ttl > 0:
        meta["ttl_seconds"] = ttl
    if promoted_at:
        meta["promoted_at"] = promoted_at
    return {"_meta": meta, "payload": data}


def _normalize_artifact_record(artifact_id: str, raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict) and isinstance(raw_value.get("_meta"), dict) and "payload" in raw_value:
        meta = dict(raw_value["_meta"])
        meta.setdefault("artifact_id", artifact_id)
        meta.setdefault("tier", "workspace")
        meta.setdefault("storage_version", _ARTIFACT_ENVELOPE_VERSION)
        return {"_meta": meta, "payload": raw_value.get("payload")}

    return _build_artifact_envelope(
        artifact_id,
        raw_value,
        tier="workspace",
        ttl=None,
    )


async def _load_artifact_record(artifact_id: str) -> dict[str, Any] | None:
    try:
        redis = await get_redis_pool()
        raw = await redis.get(_artifact_key(artifact_id))
        if raw is not None:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return _normalize_artifact_record(artifact_id, json.loads(raw))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable — checking in-process fallback: %s", exc)

    serialized = _local_fallback.get(artifact_id)
    if serialized is not None:
        return _normalize_artifact_record(artifact_id, json.loads(serialized))
    return None


def _serialize_record(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False)


async def store_engine_artifact(
    artifact_id: str,
    data: Any,
    *,
    ttl: int | None = None,
    tier: str = "workspace",
) -> None:
    """Serialize ``data`` and persist it under ``artifact_id``.

    Falls back to an in-process dict when Redis is unreachable so that
    callers never have to handle a storage error at the SSE level.
    """
    normalized_tier = str(tier or "workspace").strip().lower() or "workspace"
    if normalized_tier not in {"temp", "workspace"}:
        raise ValueError(f"Unsupported artifact tier: {tier}")

    effective_ttl = ttl
    if normalized_tier == "temp":
        effective_ttl = _TEMP_ARTIFACT_TTL_SECONDS if ttl is None else ttl
    elif ttl is not None and ttl > 0:
        effective_ttl = ttl
    else:
        effective_ttl = None

    record = _build_artifact_envelope(
        artifact_id,
        data,
        tier=normalized_tier,
        ttl=effective_ttl,
    )
    serialized = _serialize_record(record)
    try:
        redis = await get_redis_pool()
        if effective_ttl is not None and effective_ttl > 0:
            await redis.set(_artifact_key(artifact_id), serialized, ex=effective_ttl)
        else:
            await redis.set(_artifact_key(artifact_id), serialized)
        logger.debug(
            "Stored engine artifact %s in Redis (tier=%s ttl=%s)",
            artifact_id,
            normalized_tier,
            effective_ttl,
        )
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
    record = await _load_artifact_record(artifact_id)
    if record is None:
        return None
    return record.get("payload")


async def get_engine_artifact_metadata(artifact_id: str) -> dict[str, Any] | None:
    record = await _load_artifact_record(artifact_id)
    if record is None:
        return None
    return dict(record.get("_meta") or {})


async def get_engine_artifact_warning(artifact_id: str) -> str | None:
    """Return a human-readable warning when an artifact is missing or near expiry."""
    if not artifact_id:
        return None

    key = _artifact_key(artifact_id)
    metadata = await get_engine_artifact_metadata(artifact_id)
    if metadata is None:
        return f"[Warning: Artifact {artifact_id} is unavailable or has expired.]"

    if str(metadata.get("tier") or "workspace") != "temp":
        return None

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
    record = await _load_artifact_record(artifact_id)
    if record is None:
        logger.warning("patch_engine_artifact: artifact %s not found — patch skipped", artifact_id)
        return False

    existing = record.get("payload")
    if not isinstance(existing, dict):
        logger.warning("patch_engine_artifact: artifact %s payload is not a dict — patch skipped", artifact_id)
        return False

    existing.update(patch)
    record["payload"] = existing
    serialized = _serialize_record(record)

    # Try to inherit the remaining Redis TTL so the expiry clock is unchanged.
    try:
        redis = await get_redis_pool()
        key = _artifact_key(artifact_id)
        remaining_ttl = await redis.ttl(key)
        if remaining_ttl > 0:
            await redis.set(key, serialized, ex=remaining_ttl)
        else:
            await redis.set(key, serialized)
        logger.debug("Patched engine artifact %s in Redis (remaining_ttl=%ss)", artifact_id, remaining_ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable — patching in-process fallback: %s", exc)
        _local_fallback[artifact_id] = serialized

    return True


async def promote_artifact(artifact_id: str) -> bool:
    record = await _load_artifact_record(artifact_id)
    if record is None:
        logger.warning("promote_artifact: artifact %s not found", artifact_id)
        return False

    meta = dict(record.get("_meta") or {})
    meta["tier"] = "workspace"
    meta["promoted_at"] = _utc_now_iso()
    meta.pop("ttl_seconds", None)
    record["_meta"] = meta
    serialized = _serialize_record(record)

    try:
        redis = await get_redis_pool()
        key = _artifact_key(artifact_id)
        await redis.set(key, serialized)
        if hasattr(redis, "persist"):
            await redis.persist(key)
        logger.info("Promoted artifact to persistent tier: artifact_id=%s", artifact_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable — promoting artifact in in-process fallback: %s", exc)
        _local_fallback[artifact_id] = serialized

    return True

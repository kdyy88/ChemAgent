"""
Health check endpoints for monitoring infrastructure readiness.

Routes (registered at /api/health in main.py):
  GET /api/health        — overall health (Redis connectivity + worker heartbeat)
  GET /api/health/queue  — ARQ queue depth and concurrency pressure
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])

# ARQ writes a heartbeat key every ``health_check_interval`` seconds (30 s).
# If the key is older than this threshold we consider the worker unhealthy.
_WORKER_HEARTBEAT_KEY = "arq:health-check"
_WORKER_MAX_STALENESS = 90  # seconds — 3× the 30 s heartbeat interval
_ARQ_QUEUE_KEY = "arq:queue:default"
_ARQ_IN_PROGRESS_KEY = "arq:in-progress"
_ARQ_MAX_WORKERS = 4


@router.get("/")
async def health_check() -> JSONResponse:
    """Overall health: Redis PING + worker heartbeat age.

    Returns HTTP 200 when everything is healthy or HTTP 503 when a critical
    component is unavailable.
    """
    from app.core.redis_client import get_redis

    redis_status = "ok"
    worker_status = "ok"
    http_status = 200

    try:
        redis = get_redis()
        await redis.ping()
    except Exception as exc:
        redis_status = f"error: {exc}"
        http_status = 503

    if redis_status == "ok":
        try:
            redis = get_redis()
            heartbeat_raw = await redis.get(_WORKER_HEARTBEAT_KEY)
            if heartbeat_raw is None:
                worker_status = "no_heartbeat"
            else:
                # ARQ stores an ISO timestamp; we compare against wall-clock age.
                last_beat = float(heartbeat_raw)
                age = time.time() - last_beat
                if age > _WORKER_MAX_STALENESS:
                    worker_status = f"stale ({age:.0f}s old)"
        except Exception:
            # Heartbeat key may not exist during initial startup — non-fatal.
            worker_status = "unknown"

    overall = "ok" if http_status == 200 else "degraded"
    return JSONResponse(
        status_code=http_status,
        content={
            "status": overall,
            "redis": redis_status,
            "worker": worker_status,
        },
    )


@router.get("/queue")
async def queue_depth() -> dict:
    """ARQ queue depth and concurrency pressure indicator.

    pressure levels:
      "low"    — queued < 2
      "medium" — queued 2–8
      "high"   — queued > 8
    """
    from app.core.redis_client import get_redis

    redis = get_redis()
    try:
        queued = await redis.llen(_ARQ_QUEUE_KEY)  # type: ignore[misc]
        running = await redis.scard(_ARQ_IN_PROGRESS_KEY)  # type: ignore[misc]
    except Exception:
        queued = -1
        running = -1

    if queued < 0:
        pressure = "unknown"
    elif queued < 2:
        pressure = "low"
    elif queued <= 8:
        pressure = "medium"
    else:
        pressure = "high"

    return {
        "queued": queued,
        "running": running,
        "max_workers": _ARQ_MAX_WORKERS,
        "pressure": pressure,
    }

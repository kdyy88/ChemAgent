"""
ARQ WorkerSettings — entry point for the arq-worker process.

Usage (in arq-worker container):
    uv run arq app.workers.main.WorkerSettings

Key parameters:
  max_jobs=4
    Strictly limits concurrent chemistry computation to 4 jobs (matching the
    server's physical CPU count).  On a 4 GB machine with 2 uvicorn workers
    already consuming ~1.5 GB, 4 concurrent Babel/RDKit jobs fit within the
    remaining headroom.  Excess jobs queue safely in Redis — users see a
    wait status rather than an OOM crash.

  job_timeout=120
    Kill any individual job that runs longer than 2 minutes.  This prevents
    pathological molecules (e.g. enormous ring systems) from permanently
    occupying a worker slot.

  health_check_interval=30
    Worker writes a heartbeat to Redis every 30 s.  The /api/health endpoint
    reads this key to report "worker: ok | no_heartbeat".
"""

from __future__ import annotations

import os

from arq.connections import RedisSettings

from app.workers.chem_tasks import (
    task_build_3d_conformer,
    task_compute_descriptors,
    task_prepare_pdbqt,
)

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Parse redis URL into ARQ RedisSettings
def _parse_redis_settings(url: str) -> RedisSettings:
    # redis://[[username]:[password]@][host][:port][/db-number]
    url = url.replace("redis://", "")
    host_part, *db_part = url.split("/")
    host, *port_part = host_part.split(":")
    port = int(port_part[0]) if port_part else 6379
    db = int(db_part[0]) if db_part else 0
    return RedisSettings(host=host, port=port, database=db)


class WorkerSettings:
    functions = [
        task_build_3d_conformer,
        task_prepare_pdbqt,
        task_compute_descriptors,
    ]
    redis_settings = _parse_redis_settings(_REDIS_URL)
    max_jobs = 4
    job_timeout = 120           # seconds — kill stuck computation jobs
    health_check_interval = 30  # seconds — heartbeat to Redis
    keep_result = 600           # seconds — retain job result in Redis (10 min)

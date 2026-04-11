"""
ARQ worker entry point.

arq uses this path: `arq app.worker.WorkerSettings`
This module re-exports WorkerSettings from the canonical location.

Canonical location: app.services.task_runner.worker
"""
from app.services.task_runner.worker import WorkerSettings, run_chem_task  # noqa: F401

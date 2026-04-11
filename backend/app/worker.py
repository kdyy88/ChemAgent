# Backward-compatible shim.
# Canonical location: app.services.task_runner.worker
# ARQ is configured with "app.worker.WorkerSettings" — do not move this shim.
from app.services.task_runner.worker import WorkerSettings  # noqa: F401

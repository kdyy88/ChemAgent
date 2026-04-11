"""
Backward-compatibility shim.
Connection pool: app.core.redis_pool
CRUD functions: app.domain.store.artifact_store
"""
from app.core.redis_pool import *  # noqa: F401, F403
from app.domain.store.artifact_store import (  # noqa: F401
    store_task_result,
    read_task_result,
    delete_task_result,
    store_artifact,
    read_artifact,
)

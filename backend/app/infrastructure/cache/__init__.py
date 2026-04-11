"""Cache sub-package – Redis connection pool re-export.

Re-exports the singleton connection helpers from ``app.core.redis_pool``
so the rest of the codebase imports from a stable infrastructure path::

    # Preferred (new code)
    from app.infrastructure.cache import get_redis_pool, get_arq_pool

    # Legacy (still works – core module unchanged)
    from app.core.redis_pool import get_redis_pool, get_arq_pool

Responsibility boundary
-----------------------
Redis is the **hot-data tier only**.  It stores:

* Transient artifact payloads  < 1 MB  (TTL: ARTIFACT_TEMP_TTL_SECONDS)
* Distributed locks            (TTL: a few seconds)
* Rate-limit counters          (TTL: per sliding window)
* ARQ task queue state         (managed by ARQ itself)

Redis MUST NOT store:
* User-uploaded files  → use ``infrastructure.local_store``
* Workspace metadata   → use ``infrastructure.database``
* Anything without a TTL that belongs to a specific tenant permanently

TODO: implement this module
    Re-export get_redis_pool and get_arq_pool from app.core.redis_pool.
    No other logic needed here.
"""

from __future__ import annotations

# TODO: uncomment once app.core.redis_pool is stable
# from app.core.redis_pool import get_arq_pool, get_redis_pool
#
# __all__ = ["get_redis_pool", "get_arq_pool"]

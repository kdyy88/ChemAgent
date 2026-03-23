"""
Rate limiting via SlowAPI (backed by Redis).

Two limit tiers are exported:
  - ``chat_limit``    — 10 requests / minute / IP  (WebSocket upgrade guard)
  - ``compute_limit`` — 3  requests / 5 minutes / IP (heavy Babel REST endpoints)

The Redis backend ensures limits work correctly across multiple uvicorn workers
(multi-process) without inter-process shared memory.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
import os

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_REDIS_URL,
    strategy="fixed-window",
)

# Convenience string constants — used as decorator arguments in route handlers.
CHAT_RATE    = "10/minute"
COMPUTE_RATE = "3/5 minutes"

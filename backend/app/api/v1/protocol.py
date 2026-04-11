"""Backward-compatible API protocol entrypoint.

Canonical location: ``app.domain.schemas.api``.
"""

from app.domain.schemas.api import (  # noqa: F401
    EventEnvelope,
    HeartbeatClientType,
    HeartbeatMessage,
    ServerEventType,
    SessionControlMessage,
    SessionControlType,
    UserMessage,
    UserMessageType,
)

"""
Backward-compatibility shim.
Canonical location: app.domain.schemas.api
"""
from app.domain.schemas.api import (  # noqa: F401
    SessionControlType,
    UserMessageType,
    HeartbeatClientType,
    ServerEventType,
    SessionControlMessage,
    UserMessage,
    HeartbeatMessage,
    EventEnvelope,
)

from __future__ import annotations

from typing import Any

from app.agents.main_agent.runtime import get_checkpoint_db_path, get_checkpointer


def get_agent_checkpointer() -> Any:
    return get_checkpointer()


def get_agent_checkpoint_db_path() -> str | None:
    return get_checkpoint_db_path()
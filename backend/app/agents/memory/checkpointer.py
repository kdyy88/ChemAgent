"""
agents/memory/checkpointer.py — LangGraph SQLite checkpointer lifecycle.

Extracted from agents/runtime.py.  Manages the async SQLite checkpointer
used for multi-turn session persistence.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)

_CHECKPOINT_DB_ENV = "CHEMAGENT_CHECKPOINT_DB_PATH"
_DEFAULT_DB_NAME = "langgraph-checkpoints.sqlite"


def resolve_checkpoint_db_path() -> Path:
    configured = os.environ.get(_CHECKPOINT_DB_ENV, "").strip()
    default_base = Path(__file__).resolve().parents[3] / ".data"
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if not str(candidate).endswith(".sqlite") and not str(candidate).endswith(".db"):
            raise ValueError(
                f"{_CHECKPOINT_DB_ENV} must point to a .sqlite or .db file, got: {candidate}"
            )
        return candidate
    return (default_base / _DEFAULT_DB_NAME).resolve()


async def create_checkpointer(db_path: Path) -> tuple[AsyncSqliteSaver, Any]:
    """Create and enter the async SQLite checkpointer context manager.

    Returns the (checkpointer, context_manager) tuple.  The caller must call
    ``context_manager.__aexit__(None, None, None)`` on shutdown.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cm = AsyncSqliteSaver.from_conn_string(str(db_path))
    checkpointer = await cm.__aenter__()
    await checkpointer.setup()
    logger.info("Initialized LangGraph SQLite checkpointer at %s", db_path)
    return checkpointer, cm

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.graph import build_graph

logger = logging.getLogger(__name__)

_CHECKPOINT_DB_ENV = "CHEMAGENT_CHECKPOINT_DB_PATH"
_DEFAULT_DB_NAME = "langgraph-checkpoints.sqlite"

_compiled_graph: Any | None = None
_checkpointer: AsyncSqliteSaver | None = None
_checkpointer_cm: Any | None = None
_checkpoint_db_path: Path | None = None


def _resolve_checkpoint_db_path() -> Path:
    configured = os.environ.get(_CHECKPOINT_DB_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / ".data" / _DEFAULT_DB_NAME).resolve()


async def initialize_graph_runtime() -> None:
    global _compiled_graph, _checkpointer, _checkpointer_cm, _checkpoint_db_path

    if _compiled_graph is not None and _checkpointer is not None:
        return

    db_path = _resolve_checkpoint_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(db_path))
    checkpointer = await checkpointer_cm.__aenter__()
    await checkpointer.setup()

    _compiled_graph = build_graph(checkpointer=checkpointer)
    _checkpointer = checkpointer
    _checkpointer_cm = checkpointer_cm
    _checkpoint_db_path = db_path

    logger.info("Initialized LangGraph SQLite checkpointer at %s", db_path)


async def shutdown_graph_runtime() -> None:
    global _compiled_graph, _checkpointer, _checkpointer_cm

    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)

    _compiled_graph = None
    _checkpointer = None
    _checkpointer_cm = None


def get_compiled_graph() -> Any:
    if _compiled_graph is None:
        raise RuntimeError("LangGraph runtime has not been initialized.")
    return _compiled_graph


async def has_persisted_session(thread_id: str) -> bool:
    if _checkpointer is None:
        raise RuntimeError("LangGraph checkpointer has not been initialized.")
    checkpoint = await _checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
    return checkpoint is not None


def get_checkpoint_db_path() -> str | None:
    return str(_checkpoint_db_path) if _checkpoint_db_path is not None else None
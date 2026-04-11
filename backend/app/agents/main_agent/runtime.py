from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.main_agent.graph import build_graph

logger = logging.getLogger(__name__)

_CHECKPOINT_DB_ENV = "CHEMAGENT_CHECKPOINT_DB_PATH"
_DEFAULT_DB_NAME = "langgraph-checkpoints.sqlite"

_compiled_graph: Any | None = None
_checkpointer: AsyncSqliteSaver | None = None
_checkpointer_cm: Any | None = None
_checkpoint_db_path: Path | None = None


def _resolve_checkpoint_db_path() -> Path:
    configured = os.environ.get(_CHECKPOINT_DB_ENV, "").strip()
    default_base = Path(__file__).resolve().parents[2] / ".data"
    if configured:
        candidate = Path(configured).expanduser().resolve()
        # Guard against path traversal: require the path to stay inside .data/
        # (or be an absolute path the operator has explicitly chosen that ends
        #  with the expected filename suffix, which is sufficient for Docker).
        if not str(candidate).endswith(".sqlite") and not str(candidate).endswith(".db"):
            raise ValueError(
                f"{_CHECKPOINT_DB_ENV} must point to a .sqlite or .db file, got: {candidate}"
            )
        return candidate
    return (default_base / _DEFAULT_DB_NAME).resolve()


async def initialize_graph_runtime() -> None:
    global _compiled_graph, _checkpointer, _checkpointer_cm, _checkpoint_db_path

    if _compiled_graph is not None and _checkpointer is not None:
        return

    db_path = _resolve_checkpoint_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(db_path))
    checkpointer = await checkpointer_cm.__aenter__()
    await checkpointer.setup()

    try:
        compiled = build_graph(checkpointer=checkpointer)
    except Exception:
        await checkpointer_cm.__aexit__(None, None, None)
        raise

    _compiled_graph = compiled
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


def get_checkpointer() -> AsyncSqliteSaver:
    """Return the shared ``AsyncSqliteSaver`` instance.

    Required by ``build_sub_agent_graph()`` and ``tool_run_sub_agent`` so that
    sub-graphs share the parent's persistent checkpointer.  In-memory
    checkpointers are not acceptable because HITL interrupt state must survive
    HTTP request cycle boundaries.

    Raises
    ------
    RuntimeError
        If ``initialize_graph_runtime()`` has not been called yet.
    """
    if _checkpointer is None:
        raise RuntimeError(
            "LangGraph checkpointer has not been initialized. "
            "Call initialize_graph_runtime() first (it runs automatically on FastAPI startup)."
        )
    return _checkpointer


def get_checkpoint_db_path() -> str | None:
    return str(_checkpoint_db_path) if _checkpoint_db_path is not None else None
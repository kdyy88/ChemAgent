"""Checkpointer facade – exposes the active LangGraph checkpoint saver.

Current implementation: AsyncSqliteSaver (dev / single-node).

TODO: migrate to AsyncPostgresSaver for production
------------------------------------------------------
When ``settings.database_url`` points to PostgreSQL, replace
``AsyncSqliteSaver`` with ``AsyncPostgresSaver`` from the official package::

    # pyproject.toml (add when ready):
    #   langgraph-checkpoint-postgres>=2.0

    from langgraph_checkpoint_postgres import AsyncPostgresSaver
    from app.core.config import get_settings

    async def initialize_graph_runtime() -> None:
        settings = get_settings()
        if "postgresql" in settings.database_url:
            saver = AsyncPostgresSaver.from_conn_string(settings.database_url)
            await saver.setup()   # creates langgraph_checkpoints tables automatically
        else:
            saver = AsyncSqliteSaver.from_conn_string(db_path)   # current path

thread_id naming convention (multi-tenant)
------------------------------------------
The ``thread_id`` passed in ``config["configurable"]["thread_id"]`` must
include tenant and workspace to guarantee isolation across tenants::

    # Format: "{tenant_id}:{workspace_id}:{session_uuid}"
    # Example: "org_acme:ws_proj1:550e8400-e29b-41d4-a716-446655440000"

    from app.core.context import require_context
    import uuid

    ctx = require_context()
    session_id = str(uuid.uuid4())
    thread_id = f"{ctx.tenant_id}:{ctx.workspace_id}:{session_id}"
    config = {"configurable": {"thread_id": thread_id}}

This thread_id must also be stored in the ``Session.thread_id`` column in
PostgreSQL so chat history can be looked up by session.

See also: infrastructure/database/README.md (Schema → Session table)
"""

from __future__ import annotations

from typing import Any

from app.agents.main_agent.runtime import get_checkpoint_db_path, get_checkpointer


def get_agent_checkpointer() -> Any:
    return get_checkpointer()


def get_agent_checkpoint_db_path() -> str | None:
    return get_checkpoint_db_path()
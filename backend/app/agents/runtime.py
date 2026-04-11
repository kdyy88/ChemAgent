"""
Backward-compatibility shim.
Canonical location: app.agents.main_agent.runtime
"""
from app.agents.main_agent.runtime import (  # noqa: F401
    initialize_graph_runtime,
    shutdown_graph_runtime,
    get_compiled_graph,
    has_persisted_session,
    get_checkpoint_db_path,
)

"""
Chemistry tool catalog.

Assembles all LangChain @tool definitions for chemistry into namespaced
export groups.  Callers (registry.py, agent nodes) import from here.

Export groups
-------------
PURE_RDKIT_TOOLS  — core RDKit computation tools only
ALL_RDKIT_TOOLS   — RDKit + external lookups + control tools (root-agent set)
ALL_BABEL_TOOLS   — Open Babel computation tools
ALL_CHEM_TOOLS    — full catalog including sub-agent delegation
"""

from __future__ import annotations

from app.tools.chem.rdkit_tools import PURE_RDKIT_TOOLS
from app.tools.chem.pubchem import tool_pubchem_lookup
from app.tools.chem.babel_tools import ALL_BABEL_TOOLS
from app.tools.interaction.web_search import tool_web_search
from app.tools.interaction.ask_human import tool_ask_human
from app.tools.system.task_status import tool_update_task_status

# Root-agent tool set (same composition as original ALL_RDKIT_TOOLS)
ALL_RDKIT_TOOLS = [
    *PURE_RDKIT_TOOLS,
    tool_pubchem_lookup,
    tool_web_search,
    tool_ask_human,
    tool_update_task_status,
]


def _get_sub_agent_tool() -> list:
    # Lazy import to avoid circular dependency:
    # tools/chem → sub_agents/dispatcher → tools/registry → tools/chem
    from app.agents.sub_agents.dispatcher import tool_run_sub_agent  # noqa: PLC0415
    return [tool_run_sub_agent]


ALL_CHEM_TOOLS = [
    *ALL_RDKIT_TOOLS,
    *ALL_BABEL_TOOLS,
    *_get_sub_agent_tool(),
]

__all__ = [
    "PURE_RDKIT_TOOLS",
    "ALL_RDKIT_TOOLS",
    "ALL_BABEL_TOOLS",
    "ALL_CHEM_TOOLS",
    "tool_pubchem_lookup",
    "tool_web_search",
    "tool_ask_human",
    "tool_update_task_status",
]

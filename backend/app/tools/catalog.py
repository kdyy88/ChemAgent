"""
LangGraph-compatible @tool wrappers over the deterministic rdkit_ops.py layer.

These tools are used by Worker nodes (Visualizer / Analyst / Researcher) inside
the LangGraph StateGraph.  Each wrapper adds a concise docstring (used by the
LLM as a tool description) and maps the dict-based return value to a Python
object that plays well with LangChain's tool protocol.

Shadow-Lab integration note
----------------------------
These tools never validate SMILES themselves — that is exclusively the
Shadow Lab node's responsibility.  Tools call rdkit_ops and return raw dicts;
the Shadow Lab intercepts the result SMILES and runs RDKit valence checks.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Literal

from app.tools.babel.prep import ALL_BABEL_TOOLS
from app.tools.database.api import tool_fetch_chemistry_api
from app.tools.pubchem.search import ALL_PUBCHEM_TOOLS
from app.tools.rdkit import ALL_RDKIT_TOOLS
from app.tools.skills.invoke import tool_invoke_skill
from app.tools.skills.references import tool_read_skill_reference
from app.tools.system.task_control import ALL_SYSTEM_CONTROL_TOOLS
from app.tools.system.file_ops import ALL_FILE_OPS_TOOLS
from app.tools.system.shell import ALL_SHELL_TOOLS
from app.tools.system.state_tools import ALL_STATE_TOOLS
from app.tools.system.screen_tools import ALL_SCREEN_TOOLS

# Lazy import to avoid circular dependency:
# lg_tools → tools/sub_agent → tool_registry → lg_tools
def _get_sub_agent_tool() -> list:
    from app.agents.sub_agents.tool import tool_run_sub_agent  # noqa: PLC0415
    return [tool_run_sub_agent]


ALL_CHEM_TOOLS = [
    *ALL_RDKIT_TOOLS,
    *ALL_PUBCHEM_TOOLS,
    *ALL_SYSTEM_CONTROL_TOOLS,
    *ALL_BABEL_TOOLS,
    *ALL_FILE_OPS_TOOLS,
    *ALL_SHELL_TOOLS,
    *ALL_STATE_TOOLS,
    *ALL_SCREEN_TOOLS,
    # Skills infrastructure
    tool_invoke_skill,
    tool_read_skill_reference,
    tool_fetch_chemistry_api,
    *_get_sub_agent_tool(),
]

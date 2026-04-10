"""
Backward-compatibility shim.

``app.agents.lg_tools`` has been refactored into the domain-aware
``app.tools.*`` namespace.  All symbols are re-exported from their new homes.

Prefer importing directly from:
  app.tools.chem          — ALL_RDKIT_TOOLS, ALL_BABEL_TOOLS, ALL_CHEM_TOOLS
  app.tools.chem.rdkit_tools    — individual RDKit tools + shared helpers
  app.tools.chem.pubchem        — tool_pubchem_lookup
  app.tools.interaction.web_search  — tool_web_search
  app.tools.interaction.ask_human   — tool_ask_human
  app.tools.system.task_status      — tool_update_task_status
"""
from __future__ import annotations

from app.tools.chem import ALL_BABEL_TOOLS, ALL_CHEM_TOOLS, ALL_RDKIT_TOOLS  # noqa: F401
from app.tools.chem.rdkit_tools import (  # noqa: F401
    PURE_RDKIT_TOOLS,
    _check_smiles_input,
    _input_missing_error,
    _normalize_optional_text,
    _resolve_smiles_from_artifact,
    _to_text,
    tool_compute_descriptors,
    tool_compute_similarity,
    tool_evaluate_molecule,
    tool_murcko_scaffold,
    tool_render_smiles,
    tool_strip_salts,
    tool_substructure_match,
    tool_validate_smiles,
)
from app.tools.chem.pubchem import tool_pubchem_lookup  # noqa: F401
from app.tools.interaction.ask_human import AskHumanArgs, tool_ask_human  # noqa: F401
from app.tools.interaction.web_search import (  # noqa: F401
    TavilyClient,
    tool_web_search,
)
from app.tools.system.task_status import tool_update_task_status  # noqa: F401

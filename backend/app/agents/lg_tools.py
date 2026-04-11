"""
Backward-compatibility shim.
Canonical location: app.tools.rdkit.chem_tools
"""
from app.tools.rdkit.chem_tools import (  # noqa: F401
    tool_validate_smiles,
    tool_compute_descriptors,
    tool_compute_similarity,
    tool_substructure_match,
    tool_murcko_scaffold,
    tool_strip_salts,
    tool_render_smiles,
    tool_pubchem_lookup,
    tool_web_search,
    ALL_RDKIT_TOOLS,
    ALL_CHEM_TOOLS,
)
from app.tools.system.task_status import (  # noqa: F401
    tool_ask_human,
    tool_update_task_status,
)

"""
ChemAgent tool registry.

Exports ``ALL_TOOLS`` — the flat list of plain Python functions that are
bound to brain (caller) and executor via ``register_function``.

Also provides ``public_catalog()`` for the ``session.started`` WebSocket
event so the frontend knows which tools are available.
"""

from __future__ import annotations

from app.tools.chem_tools import (
    analyze_molecule,
    check_substructure,
    compute_molecular_similarity,
    draw_molecule_structure,
    extract_murcko_scaffold,
    get_molecule_smiles,
    search_web,
)

ALL_TOOLS = [
    get_molecule_smiles,
    analyze_molecule,
    extract_murcko_scaffold,
    draw_molecule_structure,
    search_web,
    compute_molecular_similarity,
    check_substructure,
]


# ── Frontend-facing metadata (enriches what the LLM schema alone provides) ───

_TOOL_META: dict[str, dict] = {
    "get_molecule_smiles": {
        "display_name": "Retrieving SMILES…",
        "category": "lookup",
        "output_kinds": ("json",),
        "tags": ("pubchem", "smiles"),
    },
    "analyze_molecule": {
        "display_name": "Analyzing Molecule…",
        "category": "analysis",
        "output_kinds": ("json",),
        "tags": ("rdkit", "lipinski", "descriptors"),
    },
    "extract_murcko_scaffold": {
        "display_name": "Extracting Scaffold…",
        "category": "analysis",
        "output_kinds": ("json", "image"),
        "tags": ("rdkit", "scaffold", "murcko"),
    },
    "draw_molecule_structure": {
        "display_name": "Drawing Structures…",
        "category": "visualization",
        "output_kinds": ("image",),
        "tags": ("rdkit", "pubchem", "structure", "visualization"),
    },
    "search_web": {
        "display_name": "Web / Literature Search",
        "category": "retrieval",
        "output_kinds": ("json",),
        "tags": ("search", "web", "literature", "drugs", "news"),
    },
    "compute_molecular_similarity": {
        "display_name": "Computing Similarity…",
        "category": "analysis",
        "output_kinds": ("json", "image"),
        "tags": ("rdkit", "similarity", "fingerprint", "tanimoto"),
    },
    "check_substructure": {
        "display_name": "Checking Substructure…",
        "category": "analysis",
        "output_kinds": ("json", "image"),
        "tags": ("rdkit", "substructure", "smarts", "pains"),
    },
}


def public_catalog() -> list[dict]:
    """Build the public tool catalog sent to the frontend in ``session.started``."""
    catalog: list[dict] = []
    for fn in ALL_TOOLS:
        meta = _TOOL_META.get(fn.__name__, {})
        # Use the first paragraph of the docstring as description
        raw_doc = fn.__doc__ or ""
        description = raw_doc.split("\n\n")[0].replace("\n", " ").strip()
        catalog.append(
            {
                "name": fn.__name__,
                "description": description,
                "displayName": meta.get(
                    "display_name", fn.__name__.replace("_", " ").title()
                ),
                "category": meta.get("category", "general"),
                "outputKinds": list(meta.get("output_kinds", ())),
                "tags": list(meta.get("tags", ())),
            }
        )
    return catalog

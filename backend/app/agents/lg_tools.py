"""
LangGraph-compatible @tool wrappers over the deterministic rdkit_ops.py layer.

These tools are used by Worker nodes (Visualizer / Analyst) inside the
LangGraph StateGraph.  Each wrapper adds a concise docstring (used by the LLM
as a tool description) and maps the dict-based return value to a Python object
that plays well with LangChain's tool protocol.

Shadow-Lab integration note
----------------------------
These tools never validate SMILES themselves — that is exclusively the
Shadow Lab node's responsibility.  Tools call rdkit_ops and return raw dicts;
the Shadow Lab intercepts the result SMILES and runs RDKit valence checks.
"""

from __future__ import annotations

import functools
import json
from typing import Annotated

from langchain_core.tools import tool

from app.chem.rdkit_ops import (
    compute_descriptors,
    compute_similarity,
    mol_to_png_b64,
    murcko_scaffold,
    strip_salts_and_neutralize,
    substructure_match,
    validate_smiles,
)
from rdkit import Chem


# ── Helper: pretty-print dict results for LLM consumption ────────────────────

def _to_text(data: dict) -> str:
    """Convert a rdkit_ops result dict to a compact JSON string for the LLM."""
    # Remove bulky base64 image fields before handing to LLM text response
    cleaned = {k: v for k, v in data.items() if "image" not in k and "structure" not in k}
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


# ── T1: Validate & Canonicalize SMILES ───────────────────────────────────────

@tool
def tool_validate_smiles(smiles: Annotated[str, "SMILES string to validate"]) -> str:
    """Validate a SMILES string and return its RDKit canonical form, formula,
    and atom/bond statistics.  Returns JSON with is_valid flag."""
    result = validate_smiles(smiles)
    return _to_text(result)


# ── T3: Comprehensive Molecular Descriptors ──────────────────────────────────

@tool
def tool_compute_descriptors(
    smiles: Annotated[str, "SMILES string of the molecule"],
    name: Annotated[str, "Common or IUPAC name of the compound (optional)"] = "",
) -> str:
    """Compute comprehensive molecular descriptors including Lipinski Rule-of-5
    (MW, LogP, HBD, HBA), TPSA, QED drug-likeness score, synthetic accessibility
    (SA Score), ring count, fraction sp3, and heavy atom count.  Returns JSON."""
    result = compute_descriptors(smiles, name)
    return _to_text(result)


# ── T4: Tanimoto Similarity ───────────────────────────────────────────────────

@tool
def tool_compute_similarity(
    smiles1: Annotated[str, "SMILES of the first molecule"],
    smiles2: Annotated[str, "SMILES of the second molecule"],
    radius: Annotated[int, "Morgan fingerprint radius (default 2 = ECFP4)"] = 2,
) -> str:
    """Compute Tanimoto similarity between two molecules using Morgan (ECFP4)
    fingerprints.  Returns a similarity score from 0.0 (dissimilar) to 1.0
    (identical) plus a human-readable interpretation.  Returns JSON."""
    result = compute_similarity(smiles1, smiles2, radius=radius)
    return _to_text(result)


# ── T5: Substructure Match + PAINS Screen ─────────────────────────────────────

@tool
def tool_substructure_match(
    smiles: Annotated[str, "SMILES of the target molecule"],
    smarts_pattern: Annotated[str, "SMARTS pattern to search for (e.g. functional group)"],
) -> str:
    """Check if a SMARTS substructure pattern matches a molecule, report match
    atom indices, and run PAINS (Pan Assay Interference) alerts screening.
    Returns JSON with matched, match_count, pains_alerts."""
    result = substructure_match(smiles, smarts_pattern)
    return _to_text(result)


# ── T6: Murcko Scaffold Extraction ───────────────────────────────────────────

@tool
def tool_murcko_scaffold(
    smiles: Annotated[str, "SMILES of the molecule to decompose"],
) -> str:
    """Extract the Bemis-Murcko scaffold and generic carbon scaffold from a
    molecule.  Useful for analysing core ring systems in a drug series.
    Returns JSON with scaffold_smiles and generic_scaffold_smiles."""
    result = murcko_scaffold(smiles)
    return _to_text(result)


# ── T9: Salt Stripping & Neutralization ───────────────────────────────────────

@tool
def tool_strip_salts(
    smiles: Annotated[str, "SMILES string possibly containing salt counterions"],
) -> str:
    """Strip salt fragments (e.g. HCl, Na+) from a molecule and neutralize
    formal charges.  Returns the largest parent fragment in canonical SMILES.
    Returns JSON with cleaned_smiles and removed_fragments."""
    result = strip_salts_and_neutralize(smiles)
    return _to_text(result)


# ── T7: 2D Structure Rendering (returns bare base64 PNG) ─────────────────────

@tool
def tool_render_smiles(
    smiles: Annotated[str, "Canonical SMILES to render as a 2D structure image"],
) -> str:
    """Render a 2D structure image for a SMILES string.  Returns a JSON object
    with a base64-encoded PNG (no data-URI prefix) in the 'image' field."""
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        return json.dumps({"is_valid": False, "error": f"RDKit 无法解析 SMILES: {smiles}"})
    image_b64 = mol_to_png_b64(mol, size=(400, 400))
    canonical = Chem.MolToSmiles(mol)
    return json.dumps({"is_valid": True, "smiles": canonical, "image": image_b64})


# ── Exported catalog for graph.py ─────────────────────────────────────────────

ALL_TOOLS = [
    tool_validate_smiles,
    tool_compute_descriptors,
    tool_compute_similarity,
    tool_substructure_match,
    tool_murcko_scaffold,
    tool_strip_salts,
    tool_render_smiles,
]

ANALYST_TOOLS = [
    tool_validate_smiles,
    tool_compute_descriptors,
    tool_compute_similarity,
    tool_substructure_match,
    tool_murcko_scaffold,
    tool_strip_salts,
]

VISUALIZER_TOOLS = [
    tool_render_smiles,
    tool_validate_smiles,
]

"""
LangGraph-compatible @tool wrappers over the deterministic babel_ops.py layer.

These tools are used by the **Prep** worker node inside the LangGraph StateGraph.
Each wrapper adds a concise docstring (used by the LLM as a tool description) and
maps the dict-based return value to a compact JSON string for LLM consumption.

Tool catalogue
──────────────
tool_convert_format          Universal format converter (SMILES ↔ SDF ↔ MOL2 ↔ PDB …)
tool_build_3d_conformer      3D conformer builder (SMILES → force-field-optimised SDF)
tool_prepare_pdbqt           Docking prep: SMILES → pH-corrected PDBQT for Smina/GNINA
tool_compute_mol_properties  Core molecular properties via Open Babel
tool_compute_partial_charges Per-atom partial charges (Gasteiger, MMFF94, QEq, EEM)
tool_list_formats            Enumeration of all Open Babel-supported format codes

Design notes
────────────
* All wrappers strip bulky binary payloads (pdbqt_content, sdf_content, zip_bytes)
  from the LLM-facing text output; the raw data is surfaced as artifacts via
  adispatch_custom_event in the node's agentic loop.
* sdf_split / sdf_merge are exposed through the REST layer only (binary I/O is
  impractical for tool-calling in the chat context).
"""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import tool

from app.chem.babel_ops import (
    build_3d_conformer,
    compute_mol_properties,
    compute_partial_charges,
    convert_format,
    list_supported_formats,
    prepare_pdbqt,
)


# ── Helper ────────────────────────────────────────────────────────────────────

_BULKY_KEYS = {"sdf_content", "pdbqt_content", "zip_bytes", "atoms"}


def _to_text(data: dict, *, keep_atoms: bool = False) -> str:
    """Serialise a babel_ops result dict to JSON, stripping large binary fields.

    ``keep_atoms`` controls whether the per-atom charge list is included (it is
    suppressed by default for LLM consumption but can be enabled for
    tool_compute_partial_charges so the model sees the charge distribution).
    """
    excluded = _BULKY_KEYS if keep_atoms else _BULKY_KEYS
    if keep_atoms:
        excluded = _BULKY_KEYS - {"atoms"}
    cleaned = {k: v for k, v in data.items() if k not in excluded}
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


# ── T1: Universal Format Converter ───────────────────────────────────────────

@tool
def tool_convert_format(
    molecule_str: Annotated[str, "Molecule string encoded in input_fmt (SMILES, InChI, SDF text, …)"],
    input_fmt: Annotated[str, "Open Babel format code for the input, e.g. 'smi', 'inchi', 'sdf'"],
    output_fmt: Annotated[str, "Open Babel format code for the output, e.g. 'sdf', 'mol2', 'pdb', 'inchi', 'inchikey'"],
) -> str:
    """Convert a molecule between any two Open Babel-supported formats.

    Supports SMILES, InChI, InChIKey, SDF, MOL2, PDB, XYZ, MOL, CML and >110 other
    formats.  Returns JSON with output string, atom counts, and is_valid flag.
    Large output (SDF, PDB) is truncated in the LLM view but dispatched as an
    artifact for the frontend.
    """
    result = convert_format(molecule_str, input_fmt, output_fmt)
    # Truncate large text outputs for LLM readability, keep metadata
    if result.get("is_valid") and result.get("output") and len(result["output"]) > 500:
        preview = result["output"][:500] + f"\n… (truncated, total {len(result['output'])} chars)"
        result = {**result, "output": preview}
    return _to_text(result)


# ── T2: 3D Conformer Builder ──────────────────────────────────────────────────

@tool
def tool_build_3d_conformer(
    smiles: Annotated[str, "Standard SMILES string of the molecule"],
    name: Annotated[str, "Optional compound name (used in SDF title / filename)"] = "",
    forcefield: Annotated[str, "Force field: 'mmff94' (default, drug-like) or 'uff' (universal)"] = "mmff94",
    steps: Annotated[int, "Conjugate-gradient optimisation steps (default 500)"] = 500,
) -> str:
    """Generate and force-field-optimise a 3D conformer from a SMILES string.

    Uses Open Babel's make3D pathway: AddHydrogens → embed 3D coordinates →
    MMFF94/UFF geometry optimisation.  Returns JSON with is_valid flag,
    atom counts, force-field energy (kcal/mol), and confirmation that 3D
    coordinates were generated.  The full SDF content is returned as an
    artifact (not included in this JSON summary to save context).
    """
    result = build_3d_conformer(smiles, name=name, forcefield=forcefield, steps=steps)
    return _to_text(result)


# ── T3: Docking PDBQT Prep ────────────────────────────────────────────────────

@tool
def tool_prepare_pdbqt(
    smiles: Annotated[str, "Standard SMILES string (2D, no explicit H required)"],
    name: Annotated[str, "Optional compound name (used in PDBQT REMARK)"] = "",
    ph: Annotated[float, "Protonation pH for AddHydrogens (default 7.4 — physiological)"] = 7.4,
) -> str:
    """Prepare a ligand PDBQT file for AutoDock-family docking (Vina, Smina, GNINA).

    Correct chemistry sequence: SMILES → AddHydrogens(pH) → make3D() →
    PDBQT (Gasteiger charges auto-assigned by OpenBabel PDBQT writer).
    Returns JSON with is_valid, rotatable_bonds, heavy_atom_count, and a
    flexibility_warning if rotatable_bonds > 10 (Vina accuracy degrades).
    The full PDBQT content is dispatched as an artifact for download.
    """
    result = prepare_pdbqt(smiles, name=name, ph=ph)
    return _to_text(result)


# ── T4: Molecular Properties (Open Babel) ────────────────────────────────────

@tool
def tool_compute_mol_properties(
    smiles: Annotated[str, "Standard SMILES string of the molecule"],
) -> str:
    """Compute core molecular properties using Open Babel: molecular formula,
    exact mass, molecular weight, formal charge, spin multiplicity, atom count,
    bond count, and rotatable bonds.

    Complements RDKit descriptors: useful when cross-checking MW/formula or
    for molecules that RDKit cannot parse but Open Babel can.
    Returns JSON with is_valid flag and all property values.
    """
    result = compute_mol_properties(smiles)
    return _to_text(result)


# ── T5: Per-Atom Partial Charges ─────────────────────────────────────────────

@tool
def tool_compute_partial_charges(
    smiles: Annotated[str, "Standard SMILES string of the molecule"],
    method: Annotated[
        str,
        "Charge model: 'gasteiger' (default, fast), 'mmff94', 'qeq', or 'eem'",
    ] = "gasteiger",
) -> str:
    """Compute per-atom partial charges using the specified Open Babel charge model.

    Returns a JSON list of heavy atoms with element symbol and partial charge,
    plus total formal charge and atom counts.  Useful for identifying reactive
    sites, building electrostatic potential maps, or preparing docking inputs.
    Supported models: gasteiger (Gasteiger-Marsili), mmff94, qeq, eem.
    """
    result = compute_partial_charges(smiles, method=method)
    # Keep heavy_atoms list but strip the full all-atoms list for brevity
    cleaned = {k: v for k, v in result.items() if k not in {"atoms", "zip_bytes"}}
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


# ── T6: Supported Format Listing ─────────────────────────────────────────────

@tool
def tool_list_formats(
    direction: Annotated[
        str,
        "Which direction to list: 'input', 'output', or 'both' (default)",
    ] = "both",
) -> str:
    """List all Open Babel-supported chemical file format codes with descriptions.

    Use this when the user asks which formats are available for conversion, or
    when you need to verify that a specific format code (e.g. 'mol2', 'xyz') is
    supported before calling tool_convert_format.
    Returns JSON with input_formats and/or output_formats lists.
    """
    result = list_supported_formats()
    direction = direction.strip().lower()
    if direction == "input":
        out = {
            "input_formats": result["input_formats"],
            "input_count": result["input_count"],
        }
    elif direction == "output":
        out = {
            "output_formats": result["output_formats"],
            "output_count": result["output_count"],
        }
    else:
        # Summarise counts and first 30 of each to avoid overwhelming context
        out = {
            "input_count": result["input_count"],
            "output_count": result["output_count"],
            "input_sample": result["input_formats"][:30],
            "output_sample": result["output_formats"][:30],
            "note": "Use direction='input' or 'output' for the full list.",
        }
    return json.dumps(out, ensure_ascii=False, indent=2)


# ── Exported catalogs for graph.py ────────────────────────────────────────────

# Full set — used for documentation & testing
ALL_BABEL_TOOLS = [
    tool_convert_format,
    tool_build_3d_conformer,
    tool_prepare_pdbqt,
    tool_compute_mol_properties,
    tool_compute_partial_charges,
    tool_list_formats,
]

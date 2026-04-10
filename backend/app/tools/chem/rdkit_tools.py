"""
RDKit chemistry tool wrappers.

LangChain @tool functions over the deterministic rdkit_ops.py layer.
All tools call services/chem/rdkit_ops.py for computation;
they add validation, artifact tracking, and LLM-friendly JSON output.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from rdkit import Chem

from app.tools.decorators import chem_tool
from app.agents.utils import strip_binary_fields
from app.services.chem.rdkit_ops import (
    _mol_to_highlighted_png_b64,
    compute_descriptors,
    compute_similarity,
    mol_to_png_b64,
    murcko_scaffold,
    strip_salts_and_neutralize,
    substructure_match,
    validate_smiles,
)

logger = logging.getLogger(__name__)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _to_text(data: dict) -> str:
    """Convert a rdkit_ops result dict to a compact JSON string for the LLM."""
    cleaned = strip_binary_fields(data)
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


_SMILES_MAX_LEN = 10_000


def _check_smiles_input(smiles: str) -> str | None:
    """Return an error JSON string if the SMILES looks unsafe, else None."""
    if len(smiles) > _SMILES_MAX_LEN:
        return json.dumps({"is_valid": False, "error": f"SMILES 超出最大长度限制（{_SMILES_MAX_LEN} 字符）"})
    if any(c in smiles for c in ("\x00", "\n", "\r")):
        return json.dumps({"is_valid": False, "error": "SMILES 包含非法控制字符"})
    if smiles.count("(") - smiles.count(")") != 0:
        return json.dumps({"is_valid": False, "error": "SMILES 括号不匹配"})
    return None


def _input_missing_error() -> str:
    return json.dumps(
        {
            "is_valid": False,
            "error": "必须至少提供 `smiles` 或 `artifact_id` 之一。",
        },
        ensure_ascii=False,
    )


def _normalize_optional_text(value: str | None) -> str:
    return value.strip() if isinstance(value, str) else ""


async def _resolve_smiles_from_artifact(artifact_id: str, fallback_smiles: str) -> tuple[str, bool]:
    """Resolve canonical SMILES from an artifact record."""
    from app.domain.stores.artifacts import get_engine_artifact  # noqa: PLC0415
    try:
        record = await get_engine_artifact(artifact_id)
        if record and isinstance(record, dict) and record.get("canonical_smiles"):
            logger.debug("Resolved SMILES from artifact %s", artifact_id)
            return record["canonical_smiles"], True
        logger.warning(
            "artifact_id=%s not found or has no canonical_smiles — falling back to raw SMILES input",
            artifact_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to resolve artifact %s: %s — falling back to raw SMILES input", artifact_id, exc)
    return fallback_smiles, False

@chem_tool(tier="L1")
def tool_validate_smiles(smiles: Annotated[str, "SMILES string to validate"]) -> str:
    """Validate a SMILES string and return its RDKit canonical form, formula,
    and atom/bond statistics.  Returns JSON with is_valid flag."""
    if err := _check_smiles_input(smiles):
        return err
    result = validate_smiles(smiles)
    return _to_text(result)


# ── T3: Comprehensive Molecular Descriptors ──────────────────────────────────

@chem_tool(tier="L1")
async def tool_evaluate_molecule(
    smiles: Annotated[str | None, "SMILES string of the molecule (optional when artifact_id is provided)"] = None,
    name: Annotated[str, "Common or IUPAC name of the compound (optional)"] = "",
    artifact_id: Annotated[str | None, "Optional artifact pointer; when set, canonical_smiles is resolved from ArtifactStore"] = None,
) -> str:
    """Evaluate a molecule atomically via validate -> descriptors pipeline.

    This tool is the preferred entrypoint for new molecule assessment because it
    guarantees sequential execution and canonical SMILES handoff, avoiding race
    conditions between separate validate/descriptor calls.
    """
    raw_smiles = _normalize_optional_text(smiles)
    raw_artifact_id = _normalize_optional_text(artifact_id)
    if not raw_smiles and not raw_artifact_id:
        return _input_missing_error()

    input_smiles = raw_smiles
    from_artifact = False
    if raw_artifact_id:
        input_smiles, from_artifact = await _resolve_smiles_from_artifact(raw_artifact_id, raw_smiles)

    if err := _check_smiles_input(input_smiles):
        return err

    validation = validate_smiles(input_smiles)
    if not validation.get("is_valid"):
        return _to_text(
            {
                "type": "evaluation",
                "is_valid": False,
                "artifact_id": None,
                "parent_artifact_id": raw_artifact_id or None,
                "from_artifact": from_artifact,
                "validation": validation,
                "error": validation.get("error", "SMILES validation failed"),
            }
        )

    canonical = validation.get("canonical_smiles", input_smiles)
    descriptors = compute_descriptors(canonical, name)

    # Immutable lineage: every chemistry state transition gets a fresh artifact
    # id.  When derived from an existing artifact, preserve provenance via
    # parent_artifact_id instead of overwriting prior state.
    created_artifact_id = f"art_{uuid.uuid4().hex[:8]}"
    from app.domain.stores.artifacts import store_engine_artifact  # noqa: PLC0415
    record = {
        "type": "molecule",
        "canonical_smiles": canonical,
        "formula": validation.get("formula") or descriptors.get("formula"),
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if raw_artifact_id:
        record["parent_artifact_id"] = raw_artifact_id
    await store_engine_artifact(created_artifact_id, record)

    return _to_text(
        {
            "type": "evaluation",
            "is_valid": bool(descriptors.get("is_valid", False)),
            "artifact_id": created_artifact_id,
            "parent_artifact_id": raw_artifact_id or None,
            "from_artifact": from_artifact,
            "validation": validation,
            "descriptors": descriptors.get("descriptors"),
            "lipinski": descriptors.get("lipinski"),
            "formula": descriptors.get("formula") or validation.get("formula"),
            "smiles": canonical,
            "name": name,
        }
    )


# ── T3: Comprehensive Molecular Descriptors ──────────────────────────────────

@chem_tool(tier="L1")
async def tool_compute_descriptors(
    smiles: Annotated[str | None, "SMILES string of the molecule (optional when artifact_id is provided)"] = None,
    name: Annotated[str, "Common or IUPAC name of the compound (optional)"] = "",
    artifact_id: Annotated[str | None, "Optional artifact pointer; when set, canonical_smiles is resolved from ArtifactStore"] = None,
) -> str:
    """Compute comprehensive molecular descriptors including Lipinski Rule-of-5
    (MW, LogP, HBD, HBA), TPSA, QED drug-likeness score, synthetic accessibility
    (SA Score), ring count, fraction sp3, and heavy atom count.

    Prefer ``tool_evaluate_molecule`` for new molecules (atomic validate->compute).
    This tool remains useful for incremental descriptor updates and supports
    artifact pointers to avoid SMILES copy drift.
    """
    raw_smiles = _normalize_optional_text(smiles)
    raw_artifact_id = _normalize_optional_text(artifact_id)
    if not raw_smiles and not raw_artifact_id:
        return _input_missing_error()

    resolved_smiles = raw_smiles
    if raw_artifact_id:
        resolved_smiles, _ = await _resolve_smiles_from_artifact(raw_artifact_id, raw_smiles)

    if err := _check_smiles_input(resolved_smiles):
        return err
    result = compute_descriptors(resolved_smiles, name)

    created_artifact_id = f"art_{uuid.uuid4().hex[:8]}"
    from app.domain.stores.artifacts import store_engine_artifact  # noqa: PLC0415
    record = {
        "type": "molecule",
        "canonical_smiles": result.get("smiles") or resolved_smiles,
        "formula": result.get("formula"),
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if raw_artifact_id:
        record["parent_artifact_id"] = raw_artifact_id
        result["parent_artifact_id"] = raw_artifact_id
    await store_engine_artifact(created_artifact_id, record)
    result["artifact_id"] = created_artifact_id
    return _to_text(result)


# ── T4: Tanimoto Similarity ───────────────────────────────────────────────────

@chem_tool(tier="L1")
def tool_compute_similarity(
    smiles1: Annotated[str, "SMILES of the first molecule"],
    smiles2: Annotated[str, "SMILES of the second molecule"],
    radius: Annotated[int, "Morgan fingerprint radius (default 2 = ECFP4)"] = 2,
) -> str:
    """Compute Tanimoto similarity between two molecules using Morgan (ECFP4)
    fingerprints.  Returns a similarity score from 0.0 (dissimilar) to 1.0
    (identical) plus a human-readable interpretation.  Returns JSON."""
    for smi in (smiles1, smiles2):
        if err := _check_smiles_input(smi):
            return err
    result = compute_similarity(smiles1, smiles2, radius=radius)
    return _to_text(result)


# ── T5: Substructure Match + PAINS Screen ─────────────────────────────────────

@chem_tool(tier="L1")
def tool_substructure_match(
    smiles: Annotated[str, "SMILES of the target molecule"],
    smarts_pattern: Annotated[str, "SMARTS pattern to search for (e.g. functional group)"],
    compound_name: Annotated[str, "Human-readable name of the compound (e.g. 'Imatinib', '伊马替尼')"] = "",
    substructure_name: Annotated[str, "Human-readable name of the substructure being searched (e.g. 'Pyrimidine', '嘧啶')"] = "",
) -> str:
    """Check if a SMARTS substructure pattern matches a molecule, report match
    atom indices, and run PAINS (Pan Assay Interference) alerts screening.
    Returns JSON with matched, match_count, pains_alerts.

    IMPORTANT: This tool automatically generates and delivers a highlighted 2D
    structure image (with the matched atoms highlighted) to the user.
    Do NOT call tool_render_smiles afterward — it would produce a redundant
    second image.  Use compound_name and substructure_name so the image title
    is human-readable (e.g. compound_name='Imatinib', substructure_name='Pyrimidine').
    """
    if err := _check_smiles_input(smiles):
        return err
    result = substructure_match(smiles, smarts_pattern)
    # Attach display names so the postprocessor can build a descriptive title.
    if compound_name:
        result["compound_name"] = compound_name
    if substructure_name:
        result["substructure_name"] = substructure_name
    return _to_text(result)


# ── T6: Murcko Scaffold Extraction ───────────────────────────────────────────

@chem_tool(tier="L1")
def tool_murcko_scaffold(
    smiles: Annotated[str, "SMILES of the molecule to decompose"],
) -> str:
    """Extract the Bemis-Murcko scaffold and generic carbon scaffold from a
    molecule.  Useful for analysing core ring systems in a drug series.
    Returns JSON with scaffold_smiles and generic_scaffold_smiles."""
    if err := _check_smiles_input(smiles):
        return err
    result = murcko_scaffold(smiles)
    return _to_text(result)


# ── T9: Salt Stripping & Neutralization ───────────────────────────────────────

@chem_tool(tier="L1")
def tool_strip_salts(
    smiles: Annotated[str, "SMILES string possibly containing salt counterions"],
) -> str:
    """Strip salt fragments (e.g. HCl, Na+) from a molecule and neutralize
    formal charges.  Returns the largest parent fragment in canonical SMILES.
    Returns JSON with cleaned_smiles and removed_fragments."""
    if err := _check_smiles_input(smiles):
        return err
    result = strip_salts_and_neutralize(smiles)
    return _to_text(result)


# ── T7: 2D Structure Rendering (returns bare base64 PNG) ─────────────────────

@chem_tool(tier="L1")
def tool_render_smiles(
    smiles: Annotated[str, "Canonical SMILES to render as a 2D structure image"],
    highlight_atoms: Annotated[list[int], "Optional atom indices to highlight in the rendered image"] = [],
    compound_name: Annotated[str, "Human-readable compound name used as the image title (e.g. 'Aspirin', '阿司匹林')"] = "",
) -> str:
    """Render a 2D structure image for a SMILES string.  Returns a JSON object
    with a base64-encoded PNG (no data-URI prefix) in the 'image' field.

    If ``highlight_atoms`` is provided, those atom indices are highlighted in
    the rendered image.  This is useful for scaffold or substructure follow-up
    rendering after a previous matching step.

    Note: If you just ran tool_substructure_match, a highlighted image was
    already generated automatically — do NOT call this tool again unless you
    need a separate plain (non-highlighted) structure image.
    Always pass compound_name so the displayed title is human-readable.
    """
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        if err := _check_smiles_input(smiles):
            return err
        return json.dumps({"is_valid": False, "error": f"RDKit 无法解析 SMILES: {smiles}"})

    normalized_highlights = sorted({
        int(atom_idx)
        for atom_idx in highlight_atoms
        if isinstance(atom_idx, int) and 0 <= atom_idx < mol.GetNumAtoms()
    })

    if normalized_highlights:
        image_b64 = _mol_to_highlighted_png_b64(mol, normalized_highlights, size=(400, 400))
    else:
        image_b64 = mol_to_png_b64(mol, size=(400, 400))

    canonical = Chem.MolToSmiles(mol)
    result: dict[str, object] = {
        "is_valid": True,
        "smiles": canonical,
        "image": image_b64,
        "highlight_atoms": normalized_highlights,
    }
    if compound_name:
        result["compound_name"] = compound_name
    return json.dumps(result, ensure_ascii=False,
    )


# ── Exported catalog for graph.py ─────────────────────────────────────────────

# ── Exported tool list ───────────────────────────────────────────────────────

PURE_RDKIT_TOOLS = [
    tool_validate_smiles,
    tool_evaluate_molecule,
    tool_compute_descriptors,
    tool_compute_similarity,
    tool_substructure_match,
    tool_murcko_scaffold,
    tool_strip_salts,
    tool_render_smiles,
]

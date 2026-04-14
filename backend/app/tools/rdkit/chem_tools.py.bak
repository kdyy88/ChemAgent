from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from rdkit import Chem

from app.tools.decorators import chem_tool
from app.agents.utils import strip_binary_fields
from app.services.chem_engine.rdkit_ops import (
    _mol_to_highlighted_png_b64,
    compute_descriptors,
    compute_similarity,
    mol_to_png_b64,
    murcko_scaffold,
    strip_salts_and_neutralize,
    substructure_match,
    validate_smiles,
)


_SMILES_MAX_LEN = 10_000


def _to_text(data: dict) -> str:
    cleaned = strip_binary_fields(data)
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


def _check_smiles_input(smiles: str) -> str | None:
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
    from app.domain.store.artifact_store import get_engine_artifact  # noqa: PLC0415

    try:
        record = await get_engine_artifact(artifact_id)
        if record and isinstance(record, dict) and record.get("canonical_smiles"):
            return record["canonical_smiles"], True
    except Exception:
        pass
    return fallback_smiles, False


@chem_tool(tier="L1")
def tool_validate_smiles(smiles: Annotated[str, "SMILES string to validate"]) -> str:
    """Validate a SMILES string and return canonicalized structure metadata."""
    if err := _check_smiles_input(smiles):
        return err
    result = validate_smiles(smiles)
    return _to_text(result)


@chem_tool(tier="L1")
async def tool_evaluate_molecule(
    smiles: Annotated[str | None, "SMILES string of the molecule (optional when artifact_id is provided)"] = None,
    name: Annotated[str, "Common or IUPAC name of the compound (optional)"] = "",
    artifact_id: Annotated[str | None, "Optional artifact pointer; when set, canonical_smiles is resolved from ArtifactStore"] = None,
) -> str:
    """Atomically validate a molecule and compute descriptors in one step."""
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

    created_artifact_id = f"art_{uuid.uuid4().hex[:8]}"
    from app.domain.store.artifact_store import store_engine_artifact  # noqa: PLC0415

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


@chem_tool(tier="L1")
async def tool_compute_descriptors(
    smiles: Annotated[str | None, "SMILES string of the molecule (optional when artifact_id is provided)"] = None,
    name: Annotated[str, "Common or IUPAC name of the compound (optional)"] = "",
    artifact_id: Annotated[str | None, "Optional artifact pointer; when set, canonical_smiles is resolved from ArtifactStore"] = None,
) -> str:
    """Compute physicochemical descriptors and Lipinski-related properties."""
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
    from app.domain.store.artifact_store import store_engine_artifact  # noqa: PLC0415

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


@chem_tool(tier="L1")
def tool_compute_similarity(
    smiles1: Annotated[str, "SMILES of the first molecule"],
    smiles2: Annotated[str, "SMILES of the second molecule"],
    radius: Annotated[int, "Morgan fingerprint radius (default 2 = ECFP4)"] = 2,
) -> str:
    """Compute Morgan-fingerprint Tanimoto similarity between two molecules."""
    for smi in (smiles1, smiles2):
        if err := _check_smiles_input(smi):
            return err
    result = compute_similarity(smiles1, smiles2, radius=radius)
    return _to_text(result)


@chem_tool(tier="L1")
def tool_substructure_match(
    smiles: Annotated[str, "SMILES of the target molecule"],
    smarts_pattern: Annotated[str, "SMARTS pattern to search for (e.g. functional group)"],
    compound_name: Annotated[str, "Human-readable name of the compound (e.g. 'Imatinib', '伊马替尼')"] = "",
    substructure_name: Annotated[str, "Human-readable name of the substructure being searched (e.g. 'Pyrimidine', '嘧啶')"] = "",
) -> str:
    """Run SMARTS substructure matching and PAINS screening on a molecule."""
    if err := _check_smiles_input(smiles):
        return err
    result = substructure_match(smiles, smarts_pattern)
    if compound_name:
        result["compound_name"] = compound_name
    if substructure_name:
        result["substructure_name"] = substructure_name
    return _to_text(result)


@chem_tool(tier="L1")
def tool_murcko_scaffold(
    smiles: Annotated[str, "SMILES of the molecule to decompose"],
) -> str:
    """Extract the Bemis-Murcko scaffold and generic scaffold."""
    if err := _check_smiles_input(smiles):
        return err
    result = murcko_scaffold(smiles)
    return _to_text(result)


@chem_tool(tier="L1")
def tool_strip_salts(
    smiles: Annotated[str, "SMILES string possibly containing salt counterions"],
) -> str:
    """Strip salt fragments and neutralize formal charges when possible."""
    if err := _check_smiles_input(smiles):
        return err
    result = strip_salts_and_neutralize(smiles)
    return _to_text(result)


@chem_tool(tier="L1")
def tool_render_smiles(
    smiles: Annotated[str, "Canonical SMILES to render as a 2D structure image"],
    highlight_atoms: Annotated[list[int], "Optional atom indices to highlight in the rendered image"] = [],
    compound_name: Annotated[str, "Human-readable compound name used as the image title (e.g. 'Aspirin', '阿司匹林')"] = "",
) -> str:
    """Render a 2D structure image for a molecule as base64 PNG JSON."""
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
    return json.dumps(result, ensure_ascii=False)


ALL_RDKIT_TOOLS = [
    tool_validate_smiles,
    tool_evaluate_molecule,
    tool_compute_descriptors,
    tool_compute_similarity,
    tool_substructure_match,
    tool_murcko_scaffold,
    tool_strip_salts,
    tool_render_smiles,
]

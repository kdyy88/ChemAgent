"""RDKit tool implementations — class-based BaseChemTool contract.

All eight RDKit tools are migrated to ``ChemComputeTool`` subclasses.

Each class:
- Declares an ``*Input`` Pydantic args_schema (SSOT for parameter docs).
- Inlines ``diagnostic_keys`` (replaces the external ``DIAGNOSTIC_SCHEMA`` dict).
- Moves parameter-format checks into ``validate_input()`` (no UI, model retries).
- Implements ``call()`` with the original execution logic.
- Exposes a module-level ``tool_*`` name via ``.as_langchain_tool()`` for
  backward-compatible imports.

Shadow-Lab integration note
----------------------------
These tools never validate SMILES themselves — that is exclusively the
Shadow Lab node's responsibility.  Tools call rdkit_ops and return raw dicts;
the Shadow Lab intercepts the result SMILES and runs RDKit valence checks.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from rdkit import Chem

from app.agents.utils import strip_binary_fields
from app.domain.schemas.workflow import ValidationResult
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
from app.tools.base import ChemComputeTool


_SMILES_MAX_LEN = 10_000


# ── Shared helpers ────────────────────────────────────────────────────────────


def _to_text(data: dict) -> str:
    cleaned = strip_binary_fields(data)
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


def _check_smiles_format(smiles: str) -> ValidationResult:
    """Basic SMILES format check (no RDKit — suitable for validate_input)."""
    if len(smiles) > _SMILES_MAX_LEN:
        return ValidationResult(
            result=False,
            message=f"SMILES 超出最大长度限制（{_SMILES_MAX_LEN} 字符）",
        )
    if any(c in smiles for c in ("\x00", "\n", "\r")):
        return ValidationResult(result=False, message="SMILES 包含非法控制字符")
    if smiles.count("(") - smiles.count(")") != 0:
        return ValidationResult(result=False, message="SMILES 括号不匹配")
    return ValidationResult(result=True)


def _normalize_optional_text(value: str | None) -> str:
    return value.strip() if isinstance(value, str) else ""


async def _resolve_smiles_from_artifact(
    artifact_id: str, fallback_smiles: str
) -> tuple[str, bool]:
    from app.domain.store.artifact_store import get_engine_artifact  # noqa: PLC0415

    try:
        record = await get_engine_artifact(artifact_id)
        if record and isinstance(record, dict) and record.get("canonical_smiles"):
            return record["canonical_smiles"], True
    except Exception:
        pass
    return fallback_smiles, False


# ── 1. tool_validate_smiles ───────────────────────────────────────────────────


class ValidateSmilesInput(BaseModel):
    smiles: str = Field(description="SMILES string to validate")


class ToolValidateSmiles(ChemComputeTool[ValidateSmilesInput, str]):
    name = "tool_validate_smiles"
    args_schema = ValidateSmilesInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    diagnostic_keys: list[str] = []
    max_result_size_chars = 2_000

    async def validate_input(self, args: ValidateSmilesInput, context: dict) -> ValidationResult:
        return _check_smiles_format(args.smiles)

    def call(self, args: ValidateSmilesInput) -> str:
        """Validate a SMILES string and return canonicalized structure metadata."""
        result = validate_smiles(args.smiles)
        return _to_text(result)


tool_validate_smiles = ToolValidateSmiles().as_langchain_tool()


# ── 2. tool_evaluate_molecule ─────────────────────────────────────────────────


class EvaluateMoleculeInput(BaseModel):
    smiles: str | None = Field(
        default=None,
        description="SMILES string of the molecule (optional when artifact_id is provided)",
    )
    name: str = Field(default="", description="Common or IUPAC name of the compound (optional)")
    artifact_id: str | None = Field(
        default=None,
        description="Optional artifact pointer; when set, canonical_smiles is resolved from ArtifactStore",
    )


class ToolEvaluateMolecule(ChemComputeTool[EvaluateMoleculeInput, str]):
    name = "tool_evaluate_molecule"
    args_schema = EvaluateMoleculeInput
    tier = "L1"
    read_only = True
    diagnostic_keys = ["qed", "sa_score"]
    max_result_size_chars = 4_000

    async def validate_input(
        self, args: EvaluateMoleculeInput, context: dict
    ) -> ValidationResult:
        raw_smiles = _normalize_optional_text(args.smiles)
        raw_artifact_id = _normalize_optional_text(args.artifact_id)
        if not raw_smiles and not raw_artifact_id:
            return ValidationResult(
                result=False,
                message="必须至少提供 `smiles` 或 `artifact_id` 之一。",
            )
        if raw_smiles and not raw_artifact_id:
            return _check_smiles_format(raw_smiles)
        return ValidationResult(result=True)

    async def call(self, args: EvaluateMoleculeInput) -> str:
        """Atomically validate a molecule and compute descriptors in one step."""
        raw_smiles = _normalize_optional_text(args.smiles)
        raw_artifact_id = _normalize_optional_text(args.artifact_id)

        input_smiles = raw_smiles
        from_artifact = False
        if raw_artifact_id:
            input_smiles, from_artifact = await _resolve_smiles_from_artifact(
                raw_artifact_id, raw_smiles
            )

        fmt = _check_smiles_format(input_smiles)
        if not fmt.result:
            return json.dumps({"is_valid": False, "error": fmt.message}, ensure_ascii=False)

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
        descriptors = compute_descriptors(canonical, args.name)

        created_artifact_id = f"art_{uuid.uuid4().hex[:8]}"
        from app.domain.store.artifact_store import store_engine_artifact  # noqa: PLC0415

        record: dict = {
            "type": "molecule",
            "canonical_smiles": canonical,
            "formula": validation.get("formula") or descriptors.get("formula"),
            "name": args.name,
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
                "name": args.name,
            }
        )


tool_evaluate_molecule = ToolEvaluateMolecule().as_langchain_tool()


# ── 3. tool_compute_descriptors ───────────────────────────────────────────────


class ComputeDescriptorsInput(BaseModel):
    smiles: str | None = Field(
        default=None,
        description="SMILES string of the molecule (optional when artifact_id is provided)",
    )
    name: str = Field(default="", description="Common or IUPAC name of the compound (optional)")
    artifact_id: str | None = Field(
        default=None,
        description="Optional artifact pointer; when set, canonical_smiles is resolved from ArtifactStore",
    )


class ToolComputeDescriptors(ChemComputeTool[ComputeDescriptorsInput, str]):
    """Pilot tool for BaseChemTool migration — SSOT for descriptor diagnostic keys."""

    name = "tool_compute_descriptors"
    args_schema = ComputeDescriptorsInput
    tier = "L1"
    read_only = True
    # diagnostic_keys is the SSOT replacing DIAGNOSTIC_SCHEMA["tool_compute_descriptors"].
    # executor._auto_patch_diagnostics() reads tool.metadata["chem_diagnostic_keys"].
    diagnostic_keys = ["mw", "tpsa", "logp", "hba", "hbd", "rotatable_bonds", "rings"]
    max_result_size_chars = 4_000

    async def validate_input(
        self, args: ComputeDescriptorsInput, context: dict
    ) -> ValidationResult:
        raw_smiles = _normalize_optional_text(args.smiles)
        raw_artifact_id = _normalize_optional_text(args.artifact_id)
        if not raw_smiles and not raw_artifact_id:
            return ValidationResult(
                result=False,
                message="必须至少提供 `smiles` 或 `artifact_id` 之一。",
            )
        if raw_smiles and not raw_artifact_id:
            return _check_smiles_format(raw_smiles)
        return ValidationResult(result=True)

    async def call(self, args: ComputeDescriptorsInput) -> str:
        """Compute physicochemical descriptors and Lipinski-related properties."""
        raw_smiles = _normalize_optional_text(args.smiles)
        raw_artifact_id = _normalize_optional_text(args.artifact_id)

        resolved_smiles = raw_smiles
        if raw_artifact_id:
            resolved_smiles, _ = await _resolve_smiles_from_artifact(raw_artifact_id, raw_smiles)

        fmt = _check_smiles_format(resolved_smiles)
        if not fmt.result:
            return json.dumps({"is_valid": False, "error": fmt.message}, ensure_ascii=False)

        result = compute_descriptors(resolved_smiles, args.name)

        created_artifact_id = f"art_{uuid.uuid4().hex[:8]}"
        from app.domain.store.artifact_store import store_engine_artifact  # noqa: PLC0415

        record: dict = {
            "type": "molecule",
            "canonical_smiles": result.get("smiles") or resolved_smiles,
            "formula": result.get("formula"),
            "name": args.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if raw_artifact_id:
            record["parent_artifact_id"] = raw_artifact_id
            result["parent_artifact_id"] = raw_artifact_id
        await store_engine_artifact(created_artifact_id, record)
        result["artifact_id"] = created_artifact_id
        return _to_text(result)


tool_compute_descriptors = ToolComputeDescriptors().as_langchain_tool()


# ── 4. tool_compute_similarity ────────────────────────────────────────────────


class ComputeSimilarityInput(BaseModel):
    smiles1: str = Field(description="SMILES of the first molecule")
    smiles2: str = Field(description="SMILES of the second molecule")
    radius: int = Field(default=2, description="Morgan fingerprint radius (default 2 = ECFP4)")


class ToolComputeSimilarity(ChemComputeTool[ComputeSimilarityInput, str]):
    name = "tool_compute_similarity"
    args_schema = ComputeSimilarityInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    diagnostic_keys = ["tanimoto"]
    max_result_size_chars = 1_000

    async def validate_input(
        self, args: ComputeSimilarityInput, context: dict
    ) -> ValidationResult:
        for smi in (args.smiles1, args.smiles2):
            result = _check_smiles_format(smi)
            if not result.result:
                return result
        return ValidationResult(result=True)

    def call(self, args: ComputeSimilarityInput) -> str:
        """Compute Morgan-fingerprint Tanimoto similarity between two molecules."""
        result = compute_similarity(args.smiles1, args.smiles2, radius=args.radius)
        return _to_text(result)


tool_compute_similarity = ToolComputeSimilarity().as_langchain_tool()


# ── 5. tool_substructure_match ────────────────────────────────────────────────


class SubstructureMatchInput(BaseModel):
    smiles: str = Field(description="SMILES of the target molecule")
    smarts_pattern: str = Field(
        description="SMARTS pattern to search for (e.g. functional group)"
    )
    compound_name: str = Field(
        default="",
        description="Human-readable name of the compound (e.g. 'Imatinib', '伊马替尼')",
    )
    substructure_name: str = Field(
        default="",
        description="Human-readable name of the substructure being searched (e.g. 'Pyrimidine', '嘧啶')",
    )


class ToolSubstructureMatch(ChemComputeTool[SubstructureMatchInput, str]):
    name = "tool_substructure_match"
    args_schema = SubstructureMatchInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    max_result_size_chars = 3_000

    async def validate_input(
        self, args: SubstructureMatchInput, context: dict
    ) -> ValidationResult:
        return _check_smiles_format(args.smiles)

    def call(self, args: SubstructureMatchInput) -> str:
        """Run SMARTS substructure matching and PAINS screening on a molecule."""
        result = substructure_match(args.smiles, args.smarts_pattern)
        if args.compound_name:
            result["compound_name"] = args.compound_name
        if args.substructure_name:
            result["substructure_name"] = args.substructure_name
        return _to_text(result)


tool_substructure_match = ToolSubstructureMatch().as_langchain_tool()


# ── 6. tool_murcko_scaffold ───────────────────────────────────────────────────


class MurckoScaffoldInput(BaseModel):
    smiles: str = Field(description="SMILES of the molecule to decompose")


class ToolMurckoScaffold(ChemComputeTool[MurckoScaffoldInput, str]):
    name = "tool_murcko_scaffold"
    args_schema = MurckoScaffoldInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    max_result_size_chars = 1_000

    async def validate_input(
        self, args: MurckoScaffoldInput, context: dict
    ) -> ValidationResult:
        return _check_smiles_format(args.smiles)

    def call(self, args: MurckoScaffoldInput) -> str:
        """Extract the Bemis-Murcko scaffold and generic scaffold."""
        result = murcko_scaffold(args.smiles)
        return _to_text(result)


tool_murcko_scaffold = ToolMurckoScaffold().as_langchain_tool()


# ── 7. tool_strip_salts ───────────────────────────────────────────────────────


class StripSaltsInput(BaseModel):
    smiles: str = Field(description="SMILES string possibly containing salt counterions")


class ToolStripSalts(ChemComputeTool[StripSaltsInput, str]):
    name = "tool_strip_salts"
    args_schema = StripSaltsInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    max_result_size_chars = 1_000

    async def validate_input(self, args: StripSaltsInput, context: dict) -> ValidationResult:
        return _check_smiles_format(args.smiles)

    def call(self, args: StripSaltsInput) -> str:
        """Strip salt fragments and neutralize formal charges when possible."""
        result = strip_salts_and_neutralize(args.smiles)
        return _to_text(result)


tool_strip_salts = ToolStripSalts().as_langchain_tool()


# ── 8. tool_render_smiles ─────────────────────────────────────────────────────


class RenderSmilesInput(BaseModel):
    smiles: str = Field(description="Canonical SMILES to render as a 2D structure image")
    highlight_atoms: list[int] = Field(
        default_factory=list,
        description="Optional atom indices to highlight in the rendered image",
    )
    compound_name: str = Field(
        default="",
        description="Human-readable compound name used as the image title (e.g. 'Aspirin', '阿司匹林')",
    )


class ToolRenderSmiles(ChemComputeTool[RenderSmilesInput, str]):
    name = "tool_render_smiles"
    args_schema = RenderSmilesInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    # Images are large — set a generous limit so base64 PNGs are not truncated.
    max_result_size_chars = 100_000

    async def validate_input(self, args: RenderSmilesInput, context: dict) -> ValidationResult:
        return _check_smiles_format(args.smiles)

    def call(self, args: RenderSmilesInput) -> str:
        """Render a 2D structure image for a molecule as base64 PNG JSON."""
        mol = Chem.MolFromSmiles(args.smiles.strip())
        if mol is None:
            fmt = _check_smiles_format(args.smiles)
            if not fmt.result:
                return json.dumps({"is_valid": False, "error": fmt.message}, ensure_ascii=False)
            return json.dumps(
                {"is_valid": False, "error": f"RDKit 无法解析 SMILES: {args.smiles}"},
                ensure_ascii=False,
            )

        normalized_highlights = sorted(
            {
                int(atom_idx)
                for atom_idx in args.highlight_atoms
                if isinstance(atom_idx, int) and 0 <= atom_idx < mol.GetNumAtoms()
            }
        )

        if normalized_highlights:
            image_b64 = _mol_to_highlighted_png_b64(mol, normalized_highlights, size=(400, 400))
        else:
            image_b64 = mol_to_png_b64(mol, size=(400, 400))

        canonical = Chem.MolToSmiles(mol)
        result: dict = {
            "is_valid": True,
            "smiles": canonical,
            "image": image_b64,
            "highlight_atoms": normalized_highlights,
        }
        if args.compound_name:
            result["compound_name"] = args.compound_name
        return json.dumps(result, ensure_ascii=False)


tool_render_smiles = ToolRenderSmiles().as_langchain_tool()


# ── Catalog ───────────────────────────────────────────────────────────────────

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

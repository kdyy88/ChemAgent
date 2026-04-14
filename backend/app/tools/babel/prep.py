"""Open Babel tool implementations -- class-based BaseChemTool contract.

All six Babel tools are migrated to ``ChemComputeTool`` subclasses.

Tool catalogue
--------------
ToolConvertFormat          Universal format converter (SMILES <-> SDF <-> MOL2 <-> PDB ...)
ToolBuild3dConformer       3D conformer builder (SMILES -> force-field-optimised SDF)
ToolPreparePdbqt           Docking prep: SMILES -> pH-corrected PDBQT for Smina/GNINA
ToolComputeMolProperties   Core molecular properties via Open Babel
ToolComputePartialCharges  Per-atom partial charges (Gasteiger, MMFF94, QEq, EEM)
ToolListFormats            Enumeration of all Open Babel-supported format codes

Design notes
------------
* All tools strip bulky binary payloads (pdbqt_content, sdf_content, zip_bytes)
  from LLM-facing output; raw data is surfaced as artifacts via custom events.
* sdf_split / sdf_merge are exposed through the REST layer only.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.domain.schemas.workflow import ValidationResult
from app.services.chem_engine.babel_ops import (
    build_3d_conformer,
    compute_mol_properties,
    compute_partial_charges,
    convert_format,
    list_supported_formats,
    prepare_pdbqt,
)
from app.tools.base import ChemComputeTool


# ── Helpers ───────────────────────────────────────────────────────────────────

_BULKY_KEYS = frozenset({"sdf_content", "pdbqt_content", "zip_bytes", "atoms"})
_SMILES_MAX_LEN = 10_000


def _to_text(data: dict, *, keep_atoms: bool = False) -> str:
    excluded = _BULKY_KEYS - ({"atoms"} if keep_atoms else set())
    cleaned = {k: v for k, v in data.items() if k not in excluded}
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


def _check_smiles(smiles: str) -> ValidationResult:
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


# ── 1. tool_convert_format ────────────────────────────────────────────────────


class ConvertFormatInput(BaseModel):
    molecule_str: str = Field(
        description="Molecule string encoded in input_fmt (SMILES, InChI, SDF text, …)"
    )
    input_fmt: str = Field(
        description="Open Babel format code for the input, e.g. 'smi', 'inchi', 'sdf'"
    )
    output_fmt: str = Field(
        description="Open Babel format code for the output, e.g. 'sdf', 'mol2', 'pdb', 'inchi', 'inchikey'"
    )


class ToolConvertFormat(ChemComputeTool[ConvertFormatInput, str]):
    """Convert a molecule between any two Open Babel-supported formats.

    Supports SMILES, InChI, InChIKey, SDF, MOL2, PDB, XYZ, MOL, CML and >110 other
    formats.  Returns JSON with output string, atom counts, and is_valid flag.
    Large output (SDF, PDB) is truncated in the LLM view but dispatched as an
    artifact for the frontend.
    """

    name = "tool_convert_format"
    args_schema = ConvertFormatInput
    tier = "L2"
    read_only = True
    is_concurrency_safe = True
    max_result_size_chars = 8_000

    async def validate_input(
        self, args: ConvertFormatInput, context: dict
    ) -> ValidationResult:
        fmt = args.input_fmt.strip().lower()
        # Only validate SMILES input at format-check stage
        if fmt in ("smi", "smiles") and args.molecule_str:
            return _check_smiles(args.molecule_str)
        if not args.molecule_str.strip():
            return ValidationResult(result=False, message="molecule_str 不能为空")
        return ValidationResult(result=True)

    def call(self, args: ConvertFormatInput) -> str:
        """Convert a molecule between chemical file formats using Open Babel."""
        result = convert_format(args.molecule_str, args.input_fmt, args.output_fmt)
        if result.get("is_valid") and result.get("output") and len(result["output"]) > 500:
            preview = result["output"][:500] + f"\n… (truncated, total {len(result['output'])} chars)"
            result = {**result, "output": preview}
        return _to_text(result)


tool_convert_format = ToolConvertFormat().as_langchain_tool()


# ── 2. tool_build_3d_conformer ────────────────────────────────────────────────


class Build3dConformerInput(BaseModel):
    smiles: str = Field(description="Standard SMILES string of the molecule")
    name: str = Field(
        default="",
        description="Optional compound name (used in SDF title / filename)",
    )
    forcefield: str = Field(
        default="mmff94",
        description="Force field: 'mmff94' (default, drug-like) or 'uff' (universal)",
    )
    steps: int = Field(
        default=500,
        description="Conjugate-gradient optimisation steps (default 500)",
    )


class ToolBuild3dConformer(ChemComputeTool[Build3dConformerInput, str]):
    """Generate and force-field-optimise a 3D conformer from a SMILES string.

    Uses Open Babel's make3D pathway: AddHydrogens → embed 3D coordinates →
    MMFF94/UFF geometry optimisation.  Returns JSON with is_valid flag,
    atom counts, force-field energy (kcal/mol), and confirmation that 3D
    coordinates were generated.  The full SDF content is returned as an
    artifact (not included in this JSON summary to save context).
    """

    name = "tool_build_3d_conformer"
    args_schema = Build3dConformerInput
    tier = "L2"
    read_only = True
    max_result_size_chars = 4_000

    async def validate_input(
        self, args: Build3dConformerInput, context: dict
    ) -> ValidationResult:
        result = _check_smiles(args.smiles)
        if not result.result:
            return result
        if args.forcefield.strip().lower() not in ("mmff94", "uff"):
            return ValidationResult(
                result=False,
                message="forcefield 必须是 'mmff94' 或 'uff'",
            )
        if not (1 <= args.steps <= 5000):
            return ValidationResult(
                result=False,
                message="steps 必须在 1 到 5000 之间",
            )
        return ValidationResult(result=True)

    def call(self, args: Build3dConformerInput) -> str:
        """Generate a 3D conformer from a SMILES string and return an artifact pointer."""
        result = build_3d_conformer(
            args.smiles,
            name=args.name,
            forcefield=args.forcefield,
            steps=args.steps,
        )
        return _to_text(result)


tool_build_3d_conformer = ToolBuild3dConformer().as_langchain_tool()


# ── 3. tool_prepare_pdbqt ─────────────────────────────────────────────────────


class PreparePdbqtInput(BaseModel):
    smiles: str = Field(
        description="Standard SMILES string (2D, no explicit H required)"
    )
    name: str = Field(
        default="",
        description="Optional compound name (used in PDBQT REMARK)",
    )
    ph: float = Field(
        default=7.4,
        description="Protonation pH for AddHydrogens (default 7.4 — physiological)",
    )


class ToolPreparePdbqt(ChemComputeTool[PreparePdbqtInput, str]):
    """Prepare a ligand PDBQT file for AutoDock-family docking (Vina, Smina, GNINA).

    Correct chemistry sequence: SMILES → AddHydrogens(pH) → make3D() →
    PDBQT (Gasteiger charges auto-assigned by OpenBabel PDBQT writer).
    Returns JSON with is_valid, rotatable_bonds, heavy_atom_count, and a
    flexibility_warning if rotatable_bonds > 10 (Vina accuracy degrades).
    The full PDBQT content is dispatched as an artifact for download.
    """

    name = "tool_prepare_pdbqt"
    args_schema = PreparePdbqtInput
    tier = "L2"
    read_only = True
    max_result_size_chars = 4_000

    async def validate_input(
        self, args: PreparePdbqtInput, context: dict
    ) -> ValidationResult:
        result = _check_smiles(args.smiles)
        if not result.result:
            return result
        if not (0.0 <= args.ph <= 14.0):
            return ValidationResult(
                result=False,
                message="ph 必须在 0.0 到 14.0 之间",
            )
        return ValidationResult(result=True)

    def call(self, args: PreparePdbqtInput) -> str:
        """Prepare a PDBQT file for AutoDock docking from a SMILES string."""
        result = prepare_pdbqt(args.smiles, name=args.name, ph=args.ph)
        return _to_text(result)


tool_prepare_pdbqt = ToolPreparePdbqt().as_langchain_tool()


# ── 4. tool_compute_mol_properties ───────────────────────────────────────────


class ComputeMolPropertiesInput(BaseModel):
    smiles: str = Field(description="Standard SMILES string of the molecule")


class ToolComputeMolProperties(ChemComputeTool[ComputeMolPropertiesInput, str]):
    """Compute core molecular properties using Open Babel: molecular formula,
    exact mass, molecular weight, formal charge, spin multiplicity, atom count,
    bond count, and rotatable bonds.

    Complements RDKit descriptors: useful when cross-checking MW/formula or
    for molecules that RDKit cannot parse but Open Babel can.
    Returns JSON with is_valid flag and all property values.
    """

    name = "tool_compute_mol_properties"
    args_schema = ComputeMolPropertiesInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    max_result_size_chars = 2_000

    async def validate_input(
        self, args: ComputeMolPropertiesInput, context: dict
    ) -> ValidationResult:
        return _check_smiles(args.smiles)

    def call(self, args: ComputeMolPropertiesInput) -> str:
        """Compute molecular properties (MW, LogP, HBD/HBA, TPSA, rotatable bonds) via Open Babel."""
        result = compute_mol_properties(args.smiles)
        return _to_text(result)


tool_compute_mol_properties = ToolComputeMolProperties().as_langchain_tool()


# ── 5. tool_compute_partial_charges ──────────────────────────────────────────


_VALID_CHARGE_METHODS = frozenset({"gasteiger", "mmff94", "qeq", "eem"})


class ComputePartialChargesInput(BaseModel):
    smiles: str = Field(description="Standard SMILES string of the molecule")
    method: str = Field(
        default="gasteiger",
        description="Charge model: 'gasteiger' (default, fast), 'mmff94', 'qeq', or 'eem'",
    )


class ToolComputePartialCharges(ChemComputeTool[ComputePartialChargesInput, str]):
    """Compute per-atom partial charges using the specified Open Babel charge model.

    Returns a JSON list of heavy atoms with element symbol and partial charge,
    plus total formal charge and atom counts.  Useful for identifying reactive
    sites, building electrostatic potential maps, or preparing docking inputs.
    Supported models: gasteiger (Gasteiger-Marsili), mmff94, qeq, eem.
    """

    name = "tool_compute_partial_charges"
    args_schema = ComputePartialChargesInput
    tier = "L2"
    read_only = True
    is_concurrency_safe = True
    max_result_size_chars = 6_000

    async def validate_input(
        self, args: ComputePartialChargesInput, context: dict
    ) -> ValidationResult:
        result = _check_smiles(args.smiles)
        if not result.result:
            return result
        if args.method.strip().lower() not in _VALID_CHARGE_METHODS:
            return ValidationResult(
                result=False,
                message=f"method 必须是以下之一: {sorted(_VALID_CHARGE_METHODS)}",
            )
        return ValidationResult(result=True)

    def call(self, args: ComputePartialChargesInput) -> str:
        """Compute partial atomic charges for a molecule using the specified charge model."""
        result = compute_partial_charges(args.smiles, args.method)
        cleaned = {k: v for k, v in result.items() if k not in {"atoms", "zip_bytes"}}
        return json.dumps(cleaned, ensure_ascii=False, indent=2)


tool_compute_partial_charges = ToolComputePartialCharges().as_langchain_tool()


# ── 6. tool_list_formats ──────────────────────────────────────────────────────


class ListFormatsInput(BaseModel):
    direction: str = Field(
        default="both",
        description="Which direction to list: 'input', 'output', or 'both' (default)",
    )


class ToolListFormats(ChemComputeTool[ListFormatsInput, str]):
    """List all Open Babel-supported chemical file format codes with descriptions.

    Use this when the user asks which formats are available for conversion, or
    when you need to verify that a specific format code (e.g. 'mol2', 'xyz') is
    supported before calling tool_convert_format.
    Returns JSON with input_formats and/or output_formats lists.
    """

    name = "tool_list_formats"
    args_schema = ListFormatsInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    max_result_size_chars = 10_000

    async def validate_input(
        self, args: ListFormatsInput, context: dict
    ) -> ValidationResult:
        if args.direction.strip().lower() not in ("input", "output", "both"):
            return ValidationResult(
                result=False,
                message="direction 必须是 'input'、'output' 或 'both'",
            )
        return ValidationResult(result=True)

    def call(self, args: ListFormatsInput) -> str:
        """List chemical file formats supported by Open Babel for import, export, or both."""
        result = list_supported_formats()
        direction = args.direction.strip().lower()
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
            out = {
                "input_count": result["input_count"],
                "output_count": result["output_count"],
                "input_sample": result["input_formats"][:30],
                "output_sample": result["output_formats"][:30],
                "note": "Use direction='input' or 'output' for the full list.",
            }
        return json.dumps(out, ensure_ascii=False, indent=2)


tool_list_formats = ToolListFormats().as_langchain_tool()


# ── Catalog ───────────────────────────────────────────────────────────────────

ALL_BABEL_TOOLS = [
    tool_convert_format,
    tool_build_3d_conformer,
    tool_prepare_pdbqt,
    tool_compute_mol_properties,
    tool_compute_partial_charges,
    tool_list_formats,
]


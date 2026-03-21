"""
Open Babel REST endpoints — Phase 1 (standalone API, no agents).

Route handlers delegate entirely to ``app.chem.babel_ops`` — no chemistry
logic lives here.  Route handlers are synchronous ``def`` (not ``async``) so
FastAPI dispatches Open Babel's blocking C++ calls through its thread-pool executor.

Routes (all under the /api prefix added in main.py):
  POST /api/babel/convert      — universal format converter  (Tool 1)
  POST /api/babel/conformer3d  — 3D conformer builder        (Tool 2)
  POST /api/babel/pdbqt        — docking PDBQT prep          (Tool 3)

Always returns HTTP 200. Use ``is_valid`` to distinguish success from failure.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.chem.babel_ops import build_3d_conformer, convert_format, prepare_pdbqt

router = APIRouter(prefix="/babel", tags=["openbabel"])


# ── Pydantic request models ───────────────────────────────────────────────────


class ConvertRequest(BaseModel):
    molecule: str = Field(
        ..., description="Molecule string in input_format (SMILES, InChI, SDF text, …)"
    )
    input_format: str = Field(
        ..., description="Open Babel format code for the input, e.g. 'smi', 'inchi', 'sdf'"
    )
    output_format: str = Field(
        ..., description="Open Babel format code for the output, e.g. 'sdf', 'mol2', 'pdb', 'inchi'"
    )


class Conformer3DRequest(BaseModel):
    smiles: str = Field(..., description="Standard SMILES string")
    name: str = Field("", description="Optional compound name (used in filename)")
    forcefield: str = Field("mmff94", description="Force field: 'mmff94' (default) or 'uff'")
    steps: int = Field(500, ge=10, le=5000, description="Conjugate-gradient optimisation steps")


class DockingPrepRequest(BaseModel):
    smiles: str = Field(..., description="Standard SMILES string")
    name: str = Field("", description="Optional compound name")
    ph: float = Field(7.4, ge=0.0, le=14.0, description="Protonation pH (default 7.4)")


# ── Route handlers ────────────────────────────────────────────────────────────


def convert(req: ConvertRequest) -> dict:
    """
    Convert a molecule between any two Open Babel-supported formats.

    Supports SMILES, InChI, InChIKey, SDF, MOL2, PDB, XYZ, MOL, and 130+ more.
    """
    return convert_format(req.molecule, req.input_format, req.output_format)


def conformer3d(req: Conformer3DRequest) -> dict:
    """
    Generate a force-field-optimised 3D conformer from a SMILES string.

    Returns an SDF file with 3D atomic coordinates ready for NGL Viewer,
    3Dmol.js, Avogadro, or any standard 3D chemistry tool.
    """
    return build_3d_conformer(req.smiles, req.name, req.forcefield, req.steps)


def pdbqt(req: DockingPrepRequest) -> dict:
    """
    Prepare a ligand PDBQT file for AutoDock-family docking (Vina, Smina, GNINA).

    Sequence: add H at target pH → generate & optimise 3D (MMFF94) →
    write PDBQT (OpenBabel auto-assigns Gasteiger partial charges).
    """
    return prepare_pdbqt(req.smiles, req.name, req.ph)


# Register after function definitions so docstrings are preserved cleanly.
router.add_api_route("/convert",     convert,     methods=["POST"])
router.add_api_route("/conformer3d", conformer3d, methods=["POST"])
router.add_api_route("/pdbqt",       pdbqt,       methods=["POST"])

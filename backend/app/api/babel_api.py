"""
Open Babel REST endpoints — Phase 1 (standalone API, no agents).

Route handlers delegate entirely to ``app.chem.babel_ops`` — no chemistry
logic lives here.  Route handlers are synchronous ``def`` (not ``async``) so
FastAPI dispatches Open Babel's blocking C++ calls through its thread-pool executor.

Routes (all under the /api prefix added in main.py):
  POST /api/babel/convert         — Tool 1: universal format converter
  POST /api/babel/conformer3d     — Tool 2: 3D conformer builder (+ energy)
  POST /api/babel/pdbqt           — Tool 3: docking PDBQT prep
  POST /api/babel/properties      — T7: molecular properties
  GET  /api/babel/formats         — Utility: supported format list
  POST /api/babel/partial-charges — F2: atom partial charge analysis
  POST /api/babel/sdf-split       — F3: split multi-mol SDF → ZIP
  POST /api/babel/sdf-merge       — F3: merge multiple SDF → single SDF

Always returns HTTP 200. Use ``is_valid`` to distinguish success from failure.
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import io

from app.chem.babel_ops import (
    build_3d_conformer,
    compute_mol_properties,
    compute_partial_charges,
    convert_format,
    list_supported_formats,
    prepare_pdbqt,
    sdf_merge,
    sdf_split,
)

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


class MolPropertiesRequest(BaseModel):
    smiles: str = Field(..., description="Standard SMILES string")


class PartialChargeRequest(BaseModel):
    smiles: str = Field(..., description="Standard SMILES string")
    method: str = Field("gasteiger", description="Charge model: gasteiger, mmff94, qeq, eem")


# ── Route handlers ────────────────────────────────────────────────────────────


def convert(req: ConvertRequest) -> dict:
    """Convert a molecule between any two Open Babel-supported formats."""
    return convert_format(req.molecule, req.input_format, req.output_format)


def conformer3d(req: Conformer3DRequest) -> dict:
    """Generate a force-field-optimised 3D conformer (now includes energy)."""
    return build_3d_conformer(req.smiles, req.name, req.forcefield, req.steps)


def pdbqt(req: DockingPrepRequest) -> dict:
    """Prepare a ligand PDBQT file for AutoDock-family docking."""
    return prepare_pdbqt(req.smiles, req.name, req.ph)


def properties(req: MolPropertiesRequest) -> dict:
    """T7: Compute core molecular properties using OpenBabel."""
    return compute_mol_properties(req.smiles)


def partial_charges(req: PartialChargeRequest) -> dict:
    """F2: Compute per-atom partial charges."""
    return compute_partial_charges(req.smiles, req.method)


def formats() -> dict:
    """Utility: List all supported input and output formats."""
    return list_supported_formats()


# ── File-based route handlers (multipart) ─────────────────────────────────────


async def handle_sdf_split(file: UploadFile = File(...)):
    """F3-Split: Upload a multi-molecule SDF → receive ZIP of individual SDFs.

    Returns the JSON report with molecule list. Download ZIP via /sdf-split-download.
    """
    content = (await file.read()).decode("utf-8", errors="replace")
    result = sdf_split(content)

    # Strip zip_bytes from the JSON response — it's served via download endpoint
    zip_bytes = result.pop("zip_bytes", b"")

    # Store zip in a module-level cache for the download endpoint
    _SDF_SPLIT_CACHE["latest_zip"] = zip_bytes
    _SDF_SPLIT_CACHE["filename"] = (file.filename or "split").replace(".sdf", "") + "_split.zip"

    return result


async def handle_sdf_split_download():
    """Download the latest split ZIP file."""
    zip_bytes = _SDF_SPLIT_CACHE.get("latest_zip", b"")
    filename = _SDF_SPLIT_CACHE.get("filename", "split.zip")

    if not zip_bytes:
        return {"is_valid": False, "error": "没有可下载的文件，请先执行拆分操作。"}

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def handle_sdf_merge(files: list[UploadFile] = File(...)):
    """F3-Merge: Upload multiple SDF files → receive merged single SDF.

    Returns JSON with merged molecule count. Download SDF via /sdf-merge-download.
    """
    sdf_contents = []
    for f in files:
        content = (await f.read()).decode("utf-8", errors="replace")
        sdf_contents.append(content)

    result = sdf_merge(sdf_contents)
    merged_sdf = result.pop("sdf_content", "")

    _SDF_MERGE_CACHE["latest_sdf"] = merged_sdf
    _SDF_MERGE_CACHE["filename"] = "merged_library.sdf"

    return result


async def handle_sdf_merge_download():
    """Download the latest merged SDF file."""
    sdf_content = _SDF_MERGE_CACHE.get("latest_sdf", "")
    filename = _SDF_MERGE_CACHE.get("filename", "merged.sdf")

    if not sdf_content:
        return {"is_valid": False, "error": "没有可下载的文件，请先执行合并操作。"}

    return StreamingResponse(
        io.BytesIO(sdf_content.encode("utf-8")),
        media_type="chemical/x-mdl-sdfile",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Simple in-memory cache for latest batch results (single-user dev environment)
_SDF_SPLIT_CACHE: dict = {}
_SDF_MERGE_CACHE: dict = {}


# ── Register all routes ───────────────────────────────────────────────────────
router.add_api_route("/convert",              convert,                    methods=["POST"])
router.add_api_route("/conformer3d",          conformer3d,                methods=["POST"])
router.add_api_route("/pdbqt",                pdbqt,                     methods=["POST"])
router.add_api_route("/properties",           properties,                methods=["POST"])
router.add_api_route("/partial-charges",      partial_charges,           methods=["POST"])
router.add_api_route("/formats",              formats,                   methods=["GET"])
router.add_api_route("/sdf-split",            handle_sdf_split,          methods=["POST"])
router.add_api_route("/sdf-split-download",   handle_sdf_split_download, methods=["GET"])
router.add_api_route("/sdf-merge",            handle_sdf_merge,          methods=["POST"])
router.add_api_route("/sdf-merge-download",   handle_sdf_merge_download, methods=["GET"])

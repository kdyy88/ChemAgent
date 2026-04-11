"""
Open Babel REST endpoints — Phase 1 (standalone API, no agents).

Route handlers delegate heavy work to the dedicated Redis-backed worker so the
FastAPI process remains lightweight and WebSocket-friendly under load.

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
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import io

from app.services.task_runner.bridge import run_via_worker
from app.domain.store.artifact_store import read_artifact

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


async def convert(req: ConvertRequest) -> dict:
    """Convert a molecule between any two Open Babel-supported formats."""
    return await run_via_worker(
        "babel.convert_format",
        {
            "molecule_str": req.molecule,
            "input_fmt": req.input_format,
            "output_fmt": req.output_format,
        },
    )


async def conformer3d(req: Conformer3DRequest) -> dict:
    """Generate a force-field-optimised 3D conformer (now includes energy)."""
    return await run_via_worker(
        "babel.build_3d_conformer",
        {
            "smiles": req.smiles,
            "name": req.name,
            "forcefield": req.forcefield,
            "steps": req.steps,
        },
    )


async def pdbqt(req: DockingPrepRequest) -> dict:
    """Prepare a ligand PDBQT file for AutoDock-family docking."""
    return await run_via_worker(
        "babel.prepare_pdbqt",
        {"smiles": req.smiles, "name": req.name, "ph": req.ph},
    )


async def properties(req: MolPropertiesRequest) -> dict:
    """T7: Compute core molecular properties using OpenBabel."""
    return await run_via_worker("babel.compute_mol_properties", {"smiles": req.smiles})


async def partial_charges(req: PartialChargeRequest) -> dict:
    """F2: Compute per-atom partial charges."""
    return await run_via_worker(
        "babel.compute_partial_charges",
        {"smiles": req.smiles, "method": req.method},
    )


async def formats() -> dict:
    """Utility: List all supported input and output formats."""
    return await run_via_worker("babel.list_supported_formats", {})


# ── File-based route handlers (multipart) ─────────────────────────────────────


async def handle_sdf_split(file: UploadFile = File(...)):
    """F3-Split: Upload a multi-molecule SDF → receive ZIP of individual SDFs.

    Returns the JSON report with molecule list. Download ZIP via /sdf-split-download.
    """
    content = (await file.read()).decode("utf-8", errors="replace")
    return await run_via_worker(
        "babel.sdf_split",
        {
            "sdf_content": content,
            "filename_base": file.filename or "split",
        },
        timeout=120.0,
    )


async def handle_sdf_split_download(result_id: str | None = None):
    """Download a previously generated split ZIP file by result_id."""
    if not result_id:
        return JSONResponse({"is_valid": False, "error": "缺少 result_id，请先执行拆分操作。"})

    artifact = await read_artifact(result_id)
    if artifact is None:
        return JSONResponse({"is_valid": False, "error": "下载结果已过期，请重新执行拆分操作。"})

    zip_bytes, meta = artifact

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type=meta["media_type"],
        headers={"Content-Disposition": f'attachment; filename="{meta["filename"]}"'},
    )


async def handle_sdf_merge(files: list[UploadFile] = File(...)):
    """F3-Merge: Upload multiple SDF files → receive merged single SDF.

    Returns JSON with merged molecule count. Download SDF via /sdf-merge-download.
    """
    sdf_contents = []
    for f in files:
        content = (await f.read()).decode("utf-8", errors="replace")
        sdf_contents.append(content)

    filename_base = files[0].filename if len(files) == 1 else "merged_library"
    return await run_via_worker(
        "babel.sdf_merge",
        {
            "sdf_contents": sdf_contents,
            "filename_base": filename_base,
        },
        timeout=120.0,
    )


async def handle_sdf_merge_download(result_id: str | None = None):
    """Download a previously generated merged SDF file by result_id."""
    if not result_id:
        return JSONResponse({"is_valid": False, "error": "缺少 result_id，请先执行合并操作。"})

    artifact = await read_artifact(result_id)
    if artifact is None:
        return JSONResponse({"is_valid": False, "error": "下载结果已过期，请重新执行合并操作。"})

    sdf_bytes, meta = artifact

    return StreamingResponse(
        io.BytesIO(sdf_bytes),
        media_type=meta["media_type"],
        headers={"Content-Disposition": f'attachment; filename="{meta["filename"]}"'},
    )


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

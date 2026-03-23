"""
Open Babel REST endpoints — v2 concurrent architecture.

Light endpoints (convert, properties, partial-charges, formats, sdf-split,
sdf-merge) remain synchronous FastAPI handlers — Open Babel's C++ calls are
fast enough that blocking the thread-pool is acceptable.

Heavy endpoints (conformer3d, pdbqt) run in asyncio.to_thread() so the
event loop is never blocked, but results are returned synchronously in the
same HTTP request.  The previous ARQ-queue pattern was removed because the
frontend expects a synchronous 200 response — it does not implement polling.

Routes (all under the /api prefix added in main.py):
  POST /api/babel/convert           — universal format converter (sync)
  POST /api/babel/conformer3d       — 3D conformer builder (sync, threaded)
  POST /api/babel/pdbqt             — docking PDBQT prep   (sync, threaded)
  POST /api/babel/properties        — molecular properties (sync)
  GET  /api/babel/formats           — supported format list (sync)
  POST /api/babel/partial-charges   — atom partial charges (sync)
  POST /api/babel/sdf-split         — split multi-mol SDF → ZIP (async upload)
  GET  /api/babel/sdf-split-download
  POST /api/babel/sdf-merge         — merge SDF files (async upload)
  GET  /api/babel/sdf-merge-download
"""

from __future__ import annotations

import asyncio
import io

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.chem.babel_ops import (
    compute_mol_properties,
    compute_partial_charges,
    convert_format,
    list_supported_formats,
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


# ── Sync light endpoints ──────────────────────────────────────────────────────


def convert(req: ConvertRequest) -> dict:
    """Convert a molecule between any two Open Babel-supported formats."""
    return convert_format(req.molecule, req.input_format, req.output_format)


def properties(req: MolPropertiesRequest) -> dict:
    """Compute core molecular properties using OpenBabel."""
    return compute_mol_properties(req.smiles)


def partial_charges(req: PartialChargeRequest) -> dict:
    """Compute per-atom partial charges."""
    return compute_partial_charges(req.smiles, req.method)


def formats() -> dict:
    """List all supported input and output formats."""
    return list_supported_formats()


# ── Heavy endpoints — synchronous, run in thread (asyncio.to_thread) ─────────
# build_3d_conformer and prepare_pdbqt are CPU-bound Open Babel calls.
# asyncio.to_thread offloads them without blocking the event loop.
# The frontend already handles synchronous 200 responses; no polling required.


async def conformer3d(req: Conformer3DRequest) -> dict:
    """Generate a 3D conformer synchronously (runs Babel in a thread)."""
    from app.chem.babel_ops import build_3d_conformer
    return await asyncio.to_thread(
        build_3d_conformer,
        req.smiles,
        req.name,
        req.forcefield,
        req.steps,
    )


async def pdbqt(req: DockingPrepRequest) -> dict:
    """Prepare a docking PDBQT file synchronously (runs Babel in a thread)."""
    from app.chem.babel_ops import prepare_pdbqt
    return await asyncio.to_thread(
        prepare_pdbqt,
        req.smiles,
        req.name,
        req.ph,
    )


# ── File-based endpoints (multipart) ──────────────────────────────────────────


async def handle_sdf_split(file: UploadFile = File(...)):
    """Upload a multi-molecule SDF → receive JSON report. Download ZIP separately."""
    content = (await file.read()).decode("utf-8", errors="replace")
    result = sdf_split(content)

    zip_bytes = result.pop("zip_bytes", b"")
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
    """Upload multiple SDF files → receive merged single SDF."""
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


_SDF_SPLIT_CACHE: dict = {}
_SDF_MERGE_CACHE: dict = {}


# ── Register routes ───────────────────────────────────────────────────────────

router.add_api_route("/convert",              convert,                    methods=["POST"])
router.add_api_route("/conformer3d",          conformer3d,                methods=["POST"])
router.add_api_route("/pdbqt",                pdbqt,                      methods=["POST"])
router.add_api_route("/properties",           properties,                 methods=["POST"])
router.add_api_route("/partial-charges",      partial_charges,            methods=["POST"])
router.add_api_route("/formats",              formats,                    methods=["GET"])
router.add_api_route("/sdf-split",            handle_sdf_split,           methods=["POST"])
router.add_api_route("/sdf-split-download",   handle_sdf_split_download,  methods=["GET"])
router.add_api_route("/sdf-merge",            handle_sdf_merge,           methods=["POST"])
router.add_api_route("/sdf-merge-download",   handle_sdf_merge_download,  methods=["GET"])

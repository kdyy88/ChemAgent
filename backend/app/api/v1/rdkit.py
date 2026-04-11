"""
RDKit REST endpoints — Phase 1 (standalone API, no agents).

Route handlers delegate heavy work to the dedicated Redis-backed worker so the
FastAPI process remains lightweight and WebSocket-friendly under load.

Routes (all under the /api/v1 prefix added in main.py):
    POST /api/v1/rdkit/analyze      — Legacy Lipinski (backward compat)
    POST /api/v1/rdkit/validate     — T1: SMILES validation & canonicalization
    POST /api/v1/rdkit/salt-strip   — T9: Salt stripping & neutralization
    POST /api/v1/rdkit/descriptors  — T3: Comprehensive descriptors (replaces Lipinski)
    POST /api/v1/rdkit/similarity   — T4: Morgan fingerprint + Tanimoto
    POST /api/v1/rdkit/substructure — T5: SMARTS substructure + PAINS
    POST /api/v1/rdkit/scaffold     — T6: Murcko scaffold extraction

Always returns HTTP 200. Use ``is_valid`` to distinguish success from failure.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.domain.schemas.api import (
    AnalyzeRequest,
    DescriptorsRequest,
    ScaffoldRequest,
    SimilarityRequest,
    SmilesRequest,
    SubstructureRequest,
)
from app.services.task_runner.bridge import run_via_worker

router = APIRouter(prefix="/rdkit", tags=["rdkit"])


# ── Route handlers ────────────────────────────────────────────────────────────


async def analyze(req: AnalyzeRequest) -> dict:
    """Legacy Lipinski analysis — kept for backward compatibility."""
    return await run_via_worker(
        "rdkit.compute_lipinski",
        {"smiles": req.smiles, "name": req.name},
    )


async def validate(req: SmilesRequest) -> dict:
    """T1: Validate a SMILES string and return canonical form + basic stats."""
    return await run_via_worker("rdkit.validate_smiles", {"smiles": req.smiles})


async def salt_strip(req: SmilesRequest) -> dict:
    """T9: Strip salt fragments and neutralize charges."""
    return await run_via_worker("rdkit.strip_salts_and_neutralize", {"smiles": req.smiles})


async def descriptors(req: DescriptorsRequest) -> dict:
    """T3: Comprehensive molecular descriptors (replaces Lipinski)."""
    return await run_via_worker(
        "rdkit.compute_descriptors",
        {"smiles": req.smiles, "name": req.name},
    )


async def similarity(req: SimilarityRequest) -> dict:
    """T4: Compute Tanimoto similarity between two molecules."""
    return await run_via_worker(
        "rdkit.compute_similarity",
        {
            "smiles1": req.smiles1,
            "smiles2": req.smiles2,
            "radius": req.radius,
            "n_bits": req.n_bits,
        },
    )


async def substructure(req: SubstructureRequest) -> dict:
    """T5: Check SMARTS substructure match and PAINS screening."""
    return await run_via_worker(
        "rdkit.substructure_match",
        {"smiles": req.smiles, "smarts_pattern": req.smarts_pattern},
    )


async def scaffold(req: ScaffoldRequest) -> dict:
    """T6: Extract Bemis-Murcko scaffold and generic scaffold."""
    return await run_via_worker("rdkit.murcko_scaffold", {"smiles": req.smiles})


# Register routes after function definitions so docstrings are preserved.
router.add_api_route("/analyze",      analyze,      methods=["POST"])
router.add_api_route("/validate",     validate,     methods=["POST"])
router.add_api_route("/salt-strip",   salt_strip,   methods=["POST"])
router.add_api_route("/descriptors",  descriptors,  methods=["POST"])
router.add_api_route("/similarity",   similarity,   methods=["POST"])
router.add_api_route("/substructure", substructure, methods=["POST"])
router.add_api_route("/scaffold",     scaffold,     methods=["POST"])

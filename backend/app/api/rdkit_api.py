"""
RDKit REST endpoints — Phase 1 (standalone API, no agents).

Route handlers delegate entirely to ``app.chem.rdkit_ops`` — no chemistry
logic lives here.  Route handlers are synchronous ``def`` (not ``async``) so
FastAPI dispatches RDKit's blocking C++ calls through its thread-pool executor.

Routes (all under the /api prefix added in main.py):
  POST /api/rdkit/analyze      — Legacy Lipinski (backward compat)
  POST /api/rdkit/validate     — T1: SMILES validation & canonicalization
  POST /api/rdkit/salt-strip   — T9: Salt stripping & neutralization
  POST /api/rdkit/descriptors  — T3: Comprehensive descriptors (replaces Lipinski)
  POST /api/rdkit/similarity   — T4: Morgan fingerprint + Tanimoto
  POST /api/rdkit/substructure — T5: SMARTS substructure + PAINS
  POST /api/rdkit/scaffold     — T6: Murcko scaffold extraction

Always returns HTTP 200. Use ``is_valid`` to distinguish success from failure.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.chem.rdkit_ops import (
    compute_descriptors,
    compute_lipinski,
    compute_similarity,
    murcko_scaffold,
    strip_salts_and_neutralize,
    substructure_match,
    validate_smiles,
)

router = APIRouter(prefix="/rdkit", tags=["rdkit"])


# ── Pydantic request models ───────────────────────────────────────────────────


class SmilesRequest(BaseModel):
    """Minimal request: just a SMILES string."""
    smiles: str


class AnalyzeRequest(BaseModel):
    smiles: str
    name: str = ""


class DescriptorsRequest(BaseModel):
    smiles: str = Field(..., description="Standard SMILES string")
    name: str = Field("", description="Optional compound name")


class SimilarityRequest(BaseModel):
    smiles1: str = Field(..., description="First molecule SMILES")
    smiles2: str = Field(..., description="Second molecule SMILES")
    radius: int = Field(2, ge=1, le=6, description="Morgan FP radius (default 2 = ECFP4)")
    n_bits: int = Field(2048, description="Fingerprint bit length")


class SubstructureRequest(BaseModel):
    smiles: str = Field(..., description="Target molecule SMILES")
    smarts_pattern: str = Field(..., description="SMARTS pattern to search for")


class ScaffoldRequest(BaseModel):
    smiles: str = Field(..., description="Standard SMILES string")


# ── Route handlers ────────────────────────────────────────────────────────────


def analyze(req: AnalyzeRequest) -> dict:
    """Legacy Lipinski analysis — kept for backward compatibility."""
    return compute_lipinski(req.smiles, req.name)


def validate(req: SmilesRequest) -> dict:
    """T1: Validate a SMILES string and return canonical form + basic stats."""
    return validate_smiles(req.smiles)


def salt_strip(req: SmilesRequest) -> dict:
    """T9: Strip salt fragments and neutralize charges."""
    return strip_salts_and_neutralize(req.smiles)


def descriptors(req: DescriptorsRequest) -> dict:
    """T3: Comprehensive molecular descriptors (replaces Lipinski)."""
    return compute_descriptors(req.smiles, req.name)


def similarity(req: SimilarityRequest) -> dict:
    """T4: Compute Tanimoto similarity between two molecules."""
    return compute_similarity(req.smiles1, req.smiles2, req.radius, req.n_bits)


def substructure(req: SubstructureRequest) -> dict:
    """T5: Check SMARTS substructure match and PAINS screening."""
    return substructure_match(req.smiles, req.smarts_pattern)


def scaffold(req: ScaffoldRequest) -> dict:
    """T6: Extract Bemis-Murcko scaffold and generic scaffold."""
    return murcko_scaffold(req.smiles)


# Register routes after function definitions so docstrings are preserved.
router.add_api_route("/analyze",      analyze,      methods=["POST"])
router.add_api_route("/validate",     validate,     methods=["POST"])
router.add_api_route("/salt-strip",   salt_strip,   methods=["POST"])
router.add_api_route("/descriptors",  descriptors,  methods=["POST"])
router.add_api_route("/similarity",   similarity,   methods=["POST"])
router.add_api_route("/substructure", substructure, methods=["POST"])
router.add_api_route("/scaffold",     scaffold,     methods=["POST"])

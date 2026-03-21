"""
RDKit REST endpoints — Phase 1 (standalone API, no agents).

Route handlers delegate entirely to ``app.chem.rdkit_ops`` — no chemistry
logic lives here.  Route handlers are synchronous ``def`` (not ``async``) so
FastAPI dispatches RDKit's blocking C++ calls through its thread-pool executor.

Routes (all under the /api prefix added in main.py):
  POST /api/rdkit/analyze   — Lipinski Rule-of-5 + TPSA + 2D structure image

Always returns HTTP 200. Use ``is_valid`` to distinguish success from failure.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.chem.rdkit_ops import compute_lipinski

router = APIRouter(prefix="/rdkit", tags=["rdkit"])


# ── Pydantic request models ───────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    smiles: str
    name: str = ""


# ── Route handlers ────────────────────────────────────────────────────────────


def analyze(req: AnalyzeRequest) -> dict:
    """
    Validate a SMILES string, compute Lipinski Rule-of-5 parameters, and
    return a 2D structure image as bare base64.

    Always returns HTTP 200. Use ``is_valid`` to distinguish success from failure —
    the frontend never needs to catch a rejected ``.json()`` for validation errors.

    Synchronous ``def`` (not async): FastAPI routes RDKit's blocking C++ calls
    through its thread-pool executor, keeping the asyncio event loop free.
    """
    return compute_lipinski(req.smiles, req.name)


router.add_api_route("/analyze", analyze, methods=["POST"])

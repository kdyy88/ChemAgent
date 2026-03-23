"""
ARQ task functions for heavy chemistry computations.

These tasks run inside the arq-worker container (separate process) where
RDKit / Babel can block the CPU without affecting the FastAPI event loop.

Design principles:
- Tasks accept plain Python types (str, int, float) — no RDKit Mol objects,
  no C++ pointers, no unpicklable objects.
- Results are stored in Redis with a 10-minute TTL so the API can poll them.
- Each task is idempotent: same SMILES + params → same result (deterministic
  force-field initial seed not guaranteed, but acceptable for conformers).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

# Lazy import of chemistry libraries — they take 2-3 s on first import.
# ARQ calls these functions in worker processes so cold-start only happens once.


async def task_build_3d_conformer(
    ctx: dict,
    *,
    smiles: str,
    name: str = "",
    forcefield: str = "mmff94",
    steps: int = 500,
) -> dict[str, Any]:
    """Generate a force-field-optimised 3D conformer for ``smiles``.

    Heavy: Open Babel ``make3D()`` runs up to ``steps`` CG optimisation steps.
    Typical runtime: 1–10 s depending on molecule size and ``steps``.
    """
    from app.chem.babel_ops import build_3d_conformer  # deferred import

    result = build_3d_conformer(smiles, name, forcefield, steps)
    return result


async def task_prepare_pdbqt(
    ctx: dict,
    *,
    smiles: str,
    name: str = "",
    ph: float = 7.4,
) -> dict[str, Any]:
    """Prepare a docking-ready PDBQT file from ``smiles``.

    Heavy: adds hydrogens + 3D conformer generation (500 MMFF94 steps) +
    Gasteiger charge assignment + PDBQT format write.
    """
    from app.chem.babel_ops import prepare_pdbqt  # deferred import

    result = prepare_pdbqt(smiles, name, ph)
    return result


async def task_compute_descriptors(
    ctx: dict,
    *,
    smiles: str,
    name: str = "",
) -> dict[str, Any]:
    """Compute comprehensive molecular descriptors for ``smiles``.

    Moderate: ~15 RDKit descriptors + QED + SA Score + 2D image render.
    """
    from app.chem.rdkit_ops import compute_descriptors  # deferred import

    result = compute_descriptors(smiles, name)
    return result

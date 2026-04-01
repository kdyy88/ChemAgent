"""
task_registry — shared task-name → callable mapping.

Imported by:
  app/core/task_bridge.py  (direct fallback when Redis is unavailable)
  app/worker.py            (ARQ worker dispatch table)

Adding a new chem operation:
  1. Add the function import here.
  2. Add the "module.function_name": fn entry to TASK_DISPATCH.
  No other file needs to change.
"""

from __future__ import annotations

from typing import Any, Callable

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
from app.chem.rdkit_ops import (
    compute_descriptors,
    compute_lipinski,
    compute_similarity,
    murcko_scaffold,
    strip_salts_and_neutralize,
    substructure_match,
    validate_smiles,
)

TaskFn = Callable[..., dict[str, Any]]

TASK_DISPATCH: dict[str, TaskFn] = {
    # ── RDKit ──────────────────────────────────────────────────────────────
    "rdkit.compute_lipinski":           compute_lipinski,
    "rdkit.validate_smiles":            validate_smiles,
    "rdkit.strip_salts_and_neutralize": strip_salts_and_neutralize,
    "rdkit.compute_descriptors":        compute_descriptors,
    "rdkit.compute_similarity":         compute_similarity,
    "rdkit.substructure_match":         substructure_match,
    "rdkit.murcko_scaffold":            murcko_scaffold,
    # ── Open Babel ─────────────────────────────────────────────────────────
    "babel.convert_format":             convert_format,
    "babel.build_3d_conformer":         build_3d_conformer,
    "babel.prepare_pdbqt":              prepare_pdbqt,
    "babel.compute_mol_properties":     compute_mol_properties,
    "babel.compute_partial_charges":    compute_partial_charges,
    "babel.list_supported_formats":     list_supported_formats,
    "babel.sdf_split":                  sdf_split,
    "babel.sdf_merge":                  sdf_merge,
}

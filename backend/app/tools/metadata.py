from __future__ import annotations

from typing import Literal

CHEM_TIER_METADATA_KEY = "chem_tier"
CHEM_TIMEOUT_METADATA_KEY = "chem_timeout_seconds"
CHEM_ROUTE_HINT_METADATA_KEY = "chem_route_hint"

ChemToolTier = Literal["L1", "L2"]

# ---------------------------------------------------------------------------
# Diagnostic schema — auto-patch to molecule_tree
# ---------------------------------------------------------------------------
# Maps tool name → list of result keys to extract into node.diagnostics.
# The executor's _auto_patch_diagnostics() reads this table and patches the
# node whose SMILES hash matches the tool's `smiles` input arg — without any
# per-tool implementation change.  Add a new row here when a new property
# tool is introduced.
DIAGNOSTIC_SCHEMA: dict[str, list[str]] = {
    "tool_compute_descriptors":     ["mw", "tpsa", "logp", "hba", "hbd", "rotatable_bonds", "rings"],
    "tool_evaluate_molecule":       ["qed", "sa_score"],
    "tool_compute_mol_properties":  ["mw", "tpsa", "logp"],
    "tool_compute_similarity":      ["tanimoto"],
    "tool_compute_partial_charges": ["gasteiger_charges"],
}

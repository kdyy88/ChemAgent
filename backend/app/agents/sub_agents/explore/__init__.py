"""
Explore sub-agent — read-only intelligence gathering.

Responsibilities:
- PubChem compound lookup
- Web/literature search
- SMILES validation (non-destructive)
- Substructure matching (read-only analysis)

Tool permission: ToolPermission.READONLY only.
Will not perform 3D conformer generation, PDBQT prep, or any write operations.
"""
from __future__ import annotations

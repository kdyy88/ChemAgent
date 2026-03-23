"""
Open Babel agent tools — Phase 2 (pending).

The computation kernels (convert_format, build_3d_conformer, prepare_pdbqt)
are stable and tested in ``app.chem.babel_ops``.  The Phase 1 REST API is
live at POST /api/babel/*.

Agent tool wrappers will be added here in Phase 2 once the API endpoints
have been exercised in production and edge-cases are understood.

Planned tools
-------------
convert_molecule_format     Universal format converter (SMILES ↔ SDF ↔ MOL2 ↔ PDB …)
generate_3d_conformer       3D conformer builder (SMILES → optimised SDF)
prepare_docking_pdbqt       Docking prep: SMILES → pH-corrected PDBQT for Smina/GNINA

Category conventions for Babel agent tools
-------------------------------------------
When registering tools here, use the following category values so the specialist
routing system can auto-assign them without editing any specialist file:

  category="conversion"   — format converters (SMILES↔SDF↔MOL2↔PDB↔InChI…)
  category="3d"           — 3D conformer generation / geometry optimization
  category="docking"      — docking preparation (PDBQT, protonation, charges)

A future Preparator specialist can then be wired as:
  specs = get_tool_specs(lambda s: s.category in {"conversion","3d","docking"})
This requires zero changes to any existing specialist file — pure plugin.
"""

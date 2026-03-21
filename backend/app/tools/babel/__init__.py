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
"""

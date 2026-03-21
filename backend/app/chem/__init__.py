"""
Pure chemistry computation kernels.

Dependency rule:  chem/ imports ONLY external libraries (RDKit, Open Babel,
                  requests, etc.) — never from app.api, app.tools, or app.agents.

Both the HTTP layer (app/api/) and the agent tool layer (app/tools/) import
from here.  This makes it trivial to unit-test chemistry logic in isolation,
without starting FastAPI or loading AG2.

Planned modules
---------------
rdkit_ops.py   — RDKit: 2D rendering, Lipinski, SMILES validation
babel_ops.py   — Open Babel: format conversion, 3D conformers, PDBQT prep
smina_ops.py   — Smina/GNINA docking helpers          (future)
xtb_ops.py     — xTB semi-empirical calculations      (future)
"""

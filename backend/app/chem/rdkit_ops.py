"""
Pure RDKit computation helpers.

No FastAPI, no agent framework, no tool registry — only RDKit and stdlib.

Re-used by:
  Phase 1  →  app/api/rdkit_api.py   (REST endpoints)
  Phase 2  →  app/tools/rdkit/       (agent tool wrappers)

Public API
----------
compute_lipinski(smiles, name)      Lipinski Rule-of-5 + TPSA + 2D image
mol_to_png_b64(mol, size)           RDKit Mol → bare base64 PNG string
"""

from __future__ import annotations

import base64
from io import BytesIO

from rdkit import Chem
from rdkit.Chem import Descriptors, Draw


# ── Low-level helpers ─────────────────────────────────────────────────────────


def mol_to_png_b64(mol: "Chem.Mol", size: tuple[int, int] = (400, 400)) -> str:
    """Render an RDKit Mol object to a bare base64-encoded PNG string.

    The returned string has NO ``data:image/png;base64,`` prefix — that prefix
    is added exclusively in the frontend JSX, consistent with the project-wide
    convention for all image artifacts.
    """
    img = Draw.MolToImage(mol, size=size)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ── Lipinski Rule-of-5 ────────────────────────────────────────────────────────


def compute_lipinski(smiles: str, name: str = "") -> dict:
    """Validate a SMILES string and compute Lipinski Rule-of-5 descriptors.

    Returns a dict matching the ``LipinskiResult | LipinskiError`` TypeScript
    discriminated union consumed by the frontend ``LipinskiCard`` component.

    Lipinski Rule-of-5 criteria (exactly 4 hard rules):
      MW   ≤ 500  Da   (molecular weight)
      LogP ≤   5       (Wildman–Crippen LogP)
      HBD  ≤   5       (hydrogen bond donors)
      HBA  ≤  10       (hydrogen bond acceptors)

    TPSA is computed and returned as a display-only reference value; it is NOT
    counted toward violations because it is not part of the original RoF-5.
    """
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        return {
            "is_valid": False,
            "error": (
                f"RDKit 无法解析 SMILES：{smiles}。"
                "请检查环闭合、芳香性、原子价态与括号层级。"
            ),
        }

    # ── Descriptors ───────────────────────────────────────────────────────────
    mw   = round(Descriptors.MolWt(mol), 2)
    logp = round(Descriptors.MolLogP(mol), 2)
    hbd  = int(Descriptors.NumHDonors(mol))
    hba  = int(Descriptors.NumHAcceptors(mol))
    tpsa = round(Descriptors.TPSA(mol), 2)

    # ── Four-criterion evaluation ─────────────────────────────────────────────
    criteria = {
        "molecular_weight": {"value": mw,   "threshold": 500, "pass": mw   <= 500},
        "log_p":            {"value": logp, "threshold":   5, "pass": logp <=   5},
        "h_bond_donors":    {"value": hbd,  "threshold":   5, "pass": hbd  <=   5},
        "h_bond_acceptors": {"value": hba,  "threshold":  10, "pass": hba  <=  10},
    }
    violations    = sum(1 for c in criteria.values() if not c["pass"])
    lipinski_pass = violations == 0

    # ── 2D image — bare base64, NO data: URI prefix ───────────────────────────
    structure_image = mol_to_png_b64(mol)

    return {
        "type":     "lipinski",          # discriminator consumed by ArtifactRenderer
        "is_valid": True,
        "smiles":   smiles.strip(),
        "name":     name.strip(),
        "properties": {
            **criteria,
            # TPSA: display-only reference, no threshold, no pass/fail
            "tpsa": {"value": tpsa, "unit": "Å²"},
        },
        "lipinski_pass":   lipinski_pass,
        "violations":      violations,
        "structure_image": structure_image,   # bare base64 string
    }

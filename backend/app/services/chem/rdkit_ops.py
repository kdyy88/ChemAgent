"""
Pure RDKit computation helpers.

No FastAPI, no agent framework, no tool registry — only RDKit and stdlib.

Re-used by:
  Phase 1  →  app/api/rdkit_api.py   (REST endpoints)
  Phase 2  →  app/tools/rdkit/       (agent tool wrappers)

Public API
----------
mol_to_png_b64(mol, size)                   RDKit Mol → bare base64 PNG string
compute_lipinski(smiles, name)              Lipinski Rule-of-5 + TPSA + 2D image  (legacy)
validate_smiles(smiles)                     T1: SMILES validation & canonicalization
strip_salts_and_neutralize(smiles)          T9: Salt stripping & neutralization
compute_descriptors(smiles, name)           T3: Comprehensive descriptors (replaces Lipinski)
compute_similarity(smiles1, smiles2, …)     T4: Morgan fingerprint + Tanimoto
substructure_match(smiles, smarts_pattern)  T5: SMARTS substructure + PAINS
murcko_scaffold(smiles)                     T6: Bemis-Murcko scaffold extraction
"""

from __future__ import annotations

import base64
from io import BytesIO

from rdkit import Chem
from rdkit.Chem import (
    AllChem,
    Descriptors,
    Draw,
    FilterCatalog,
    QED,
    SaltRemover,
    rdFingerprintGenerator,
    rdMolDescriptors,
)
from rdkit.Chem.Scaffolds import MurckoScaffold
from rdkit.DataStructs import TanimotoSimilarity
from rdkit.Contrib.SA_Score import sascorer


# ── Singleton: PAINS FilterCatalog (expensive, load once) ─────────────────────

_PAINS_PARAMS = FilterCatalog.FilterCatalogParams()
_PAINS_PARAMS.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
_PAINS_CATALOG = FilterCatalog.FilterCatalog(_PAINS_PARAMS)

# ── Singleton: SaltRemover ────────────────────────────────────────────────────

_SALT_REMOVER = SaltRemover.SaltRemover()

# ── Neutralization patterns ───────────────────────────────────────────────────
# Converts charged groups back to neutral form where chemically reasonable.

_NEUTRALIZE_RXNS = [
    # [N+](=O)[O-] → [N+](=O)[O-]  (nitro — keep as-is, skip)
    (Chem.MolFromSmarts("[n+;H]"), Chem.MolFromSmiles("n")),
    (Chem.MolFromSmarts("[N+;!H0]"), Chem.MolFromSmiles("N")),
    (Chem.MolFromSmarts("[$([O-]);!$([O-][#7])]"), Chem.MolFromSmiles("O")),
    (Chem.MolFromSmarts("[S-;X1]"), Chem.MolFromSmiles("S")),
    (Chem.MolFromSmarts("[$([N-;X2]S(=O)=O)]"), Chem.MolFromSmiles("N")),
    (Chem.MolFromSmarts("[$([N-;X2][C,N]=C)]"), Chem.MolFromSmiles("N")),
    (Chem.MolFromSmarts("[n-]"), Chem.MolFromSmiles("[nH]")),
    (Chem.MolFromSmarts("[$([S-]=O)]"), Chem.MolFromSmiles("S")),
    (Chem.MolFromSmarts("[$([N-]C=O)]"), Chem.MolFromSmiles("N")),
]


# ── Low-level helpers ─────────────────────────────────────────────────────────


def _canonicalize(smiles: str) -> tuple[Chem.Mol | None, str, str]:
    """Canonicalize a SMILES string.

    Returns (mol, canonical_smiles, error_message).
    If parsing fails, mol is None and canonical_smiles is empty.
    """
    cleaned = smiles.strip()
    mol = Chem.MolFromSmiles(cleaned)
    if mol is None:
        return None, "", (
            f"RDKit 无法解析 SMILES：{cleaned}。"
            "请检查环闭合、芳香性、原子价态与括号层级。"
        )
    return mol, Chem.MolToSmiles(mol), ""


def _neutralize(mol: Chem.Mol) -> Chem.Mol:
    """Neutralize charges in a molecule where chemically appropriate."""
    mol = Chem.RWMol(mol)
    for reactant, product in _NEUTRALIZE_RXNS:
        while mol.HasSubstructMatch(reactant):
            idx = mol.GetSubstructMatch(reactant)[0]
            atom = mol.GetAtomWithIdx(idx)
            target = product.GetAtomWithIdx(0)
            atom.SetFormalCharge(target.GetFormalCharge())
            atom.SetNumExplicitHs(target.GetNumExplicitHs())
            atom.SetNoImplicit(target.GetNoImplicit())
    return mol.GetMol()


def mol_to_png_b64(mol: Chem.Mol, size: tuple[int, int] = (400, 400)) -> str:
    """Render an RDKit Mol object to a bare base64-encoded PNG string.

    The returned string has NO ``data:image/png;base64,`` prefix — that prefix
    is added exclusively in the frontend JSX, consistent with the project-wide
    convention for all image artifacts.
    """
    img = Draw.MolToImage(mol, size=size)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _mol_to_highlighted_png_b64(
    mol: Chem.Mol,
    atom_indices: list[int],
    size: tuple[int, int] = (400, 400),
) -> str:
    """Render a mol with specific atoms highlighted in red."""
    drawer = Draw.rdMolDraw2D.MolDraw2DCairo(*size)
    drawer.drawOptions().highlightColour = (1.0, 0.4, 0.4, 0.5)
    drawer.DrawMolecule(
        mol,
        highlightAtoms=atom_indices,
    )
    drawer.FinishDrawing()
    png_bytes = drawer.GetDrawingText()
    return base64.b64encode(png_bytes).decode("utf-8")


# ── T1: SMILES Validation & Canonicalization ──────────────────────────────────


def validate_smiles(smiles: str) -> dict:
    """Validate a SMILES string and return canonical form + basic statistics.

    Returns dict matching ``ValidateResult | ValidateError`` TypeScript union.
    """
    mol, canonical, error = _canonicalize(smiles)
    if mol is None:
        return {"type": "validate", "is_valid": False, "error": error}

    formula = rdMolDescriptors.CalcMolFormula(mol)
    return {
        "type": "validate",
        "is_valid": True,
        "input_smiles": smiles.strip(),
        "canonical_smiles": canonical,
        "formula": formula,
        "atom_count": mol.GetNumAtoms(),
        "heavy_atom_count": mol.GetNumHeavyAtoms(),
        "bond_count": mol.GetNumBonds(),
        "ring_count": Descriptors.RingCount(mol),
        "is_canonical": smiles.strip() == canonical,
    }


# ── T9: Salt Stripping & Neutralization ───────────────────────────────────────


def strip_salts_and_neutralize(smiles: str) -> dict:
    """Strip salt fragments and neutralize charges.

    Returns the largest (parent) fragment after stripping, neutralized.
    """
    mol, _, error = _canonicalize(smiles)
    if mol is None:
        return {"type": "salt_strip", "is_valid": False, "error": error}

    original_smiles = Chem.MolToSmiles(mol)

    # Step 1: Split into fragments, keep the largest (parent molecule)
    try:
        stripped = _SALT_REMOVER.StripMol(mol, dontRemoveEverything=True)
    except (ValueError, RuntimeError, AttributeError):
        stripped = mol

    # Step 2: If multi-fragment, pick the heaviest fragment as parent
    frags = Chem.GetMolFrags(stripped, asMols=True, sanitizeFrags=True)
    if frags:
        parent = max(frags, key=lambda f: f.GetNumHeavyAtoms())
    else:
        parent = stripped

    # Step 3: Neutralize charges
    neutralized = _neutralize(parent)
    cleaned_smiles = Chem.MolToSmiles(neutralized)

    # Identify removed fragments
    original_frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)
    removed = []
    if len(original_frags) > 1:
        parent_smi = Chem.MolToSmiles(parent)
        for frag in original_frags:
            frag_smi = Chem.MolToSmiles(frag)
            if frag_smi != parent_smi:
                removed.append(frag_smi)

    return {
        "type": "salt_strip",
        "is_valid": True,
        "original_smiles": original_smiles,
        "cleaned_smiles": cleaned_smiles,
        "removed_fragments": removed,
        "charge_neutralized": original_smiles != cleaned_smiles,
        "had_salts": len(removed) > 0,
        "parent_formula": rdMolDescriptors.CalcMolFormula(neutralized),
        "parent_heavy_atoms": neutralized.GetNumHeavyAtoms(),
        "structure_image": mol_to_png_b64(neutralized),
    }


# ── T3: Comprehensive Molecular Descriptors ──────────────────────────────────


def compute_descriptors(smiles: str, name: str = "") -> dict:
    """Compute comprehensive molecular descriptors — replaces old compute_lipinski.

    Includes Lipinski Ro5 evaluation, QED drug-likeness, SA Score, and 15+
    physicochemical properties, plus a 2D structure image.
    """
    mol, canonical, error = _canonicalize(smiles)
    if mol is None:
        return {"type": "descriptors", "is_valid": False, "error": error}

    # ── Core descriptors ──────────────────────────────────────────────────
    mw = round(Descriptors.MolWt(mol), 2)
    logp = round(Descriptors.MolLogP(mol), 2)
    hbd = int(Descriptors.NumHDonors(mol))
    hba = int(Descriptors.NumHAcceptors(mol))
    tpsa = round(Descriptors.TPSA(mol), 2)
    rotatable_bonds = int(Descriptors.NumRotatableBonds(mol))
    ring_count = Descriptors.RingCount(mol)
    aromatic_rings = Descriptors.NumAromaticRings(mol)
    fsp3 = round(Descriptors.FractionCSP3(mol), 3)
    heavy_atom_count = mol.GetNumHeavyAtoms()
    formula = rdMolDescriptors.CalcMolFormula(mol)

    # ── QED (Quantitative Estimate of Drug-likeness) ──────────────────────
    qed_score = round(QED.qed(mol), 3)

    # ── SA Score (Synthetic Accessibility, 1=easy … 10=hard) ──────────────
    sa_score = round(sascorer.calculateScore(mol), 2)

    # ── Lipinski four-criterion evaluation ────────────────────────────────
    lipinski_criteria = {
        "molecular_weight": {"value": mw, "threshold": 500, "pass": mw <= 500},
        "log_p": {"value": logp, "threshold": 5, "pass": logp <= 5},
        "h_bond_donors": {"value": hbd, "threshold": 5, "pass": hbd <= 5},
        "h_bond_acceptors": {"value": hba, "threshold": 10, "pass": hba <= 10},
    }
    violations = sum(1 for c in lipinski_criteria.values() if not c["pass"])
    lipinski_pass = violations == 0

    # ── Structure image ───────────────────────────────────────────────────
    structure_image = mol_to_png_b64(mol)

    return {
        "type": "descriptors",
        "is_valid": True,
        "smiles": canonical,
        "name": name.strip(),
        "formula": formula,
        # All descriptors in one flat section
        "descriptors": {
            "molecular_weight": mw,
            "log_p": logp,
            "h_bond_donors": hbd,
            "h_bond_acceptors": hba,
            "tpsa": tpsa,
            "rotatable_bonds": rotatable_bonds,
            "ring_count": ring_count,
            "aromatic_rings": aromatic_rings,
            "fraction_csp3": fsp3,
            "heavy_atom_count": heavy_atom_count,
            "qed": qed_score,
            "sa_score": sa_score,
        },
        # Lipinski evaluation (subset of descriptors, kept for display badge)
        "lipinski": {
            "criteria": lipinski_criteria,
            "pass": lipinski_pass,
            "violations": violations,
        },
        "structure_image": structure_image,
    }


# ── Legacy API: compute_lipinski (backward compat for agent tool wrapper) ─────


def compute_lipinski(smiles: str, name: str = "") -> dict:
    """Legacy Lipinski Rule-of-5 — delegates to compute_descriptors internally.

    Kept for backward compatibility with the existing agent tool wrapper
    ``app.tools.rdkit.analysis``.
    """
    result = compute_descriptors(smiles, name)
    if not result["is_valid"]:
        return {"is_valid": False, "error": result["error"]}

    d = result["descriptors"]
    lip = result["lipinski"]
    return {
        "type": "lipinski",
        "is_valid": True,
        "smiles": result["smiles"],
        "name": result["name"],
        "properties": {
            "molecular_weight": lip["criteria"]["molecular_weight"],
            "log_p": lip["criteria"]["log_p"],
            "h_bond_donors": lip["criteria"]["h_bond_donors"],
            "h_bond_acceptors": lip["criteria"]["h_bond_acceptors"],
            "tpsa": {"value": d["tpsa"], "unit": "Å²"},
        },
        "lipinski_pass": lip["pass"],
        "violations": lip["violations"],
        "structure_image": result["structure_image"],
    }


# ── T4: Molecular Similarity (Morgan Fingerprint + Tanimoto) ──────────────────


def compute_similarity(
    smiles1: str,
    smiles2: str,
    radius: int = 2,
    n_bits: int = 2048,
) -> dict:
    """Compute Tanimoto similarity between two molecules using Morgan fingerprints.

    Parameters
    ----------
    smiles1  : First molecule SMILES.
    smiles2  : Second molecule SMILES.
    radius   : Morgan fingerprint radius (default 2 = ECFP4).
    n_bits   : Fingerprint bit length (default 2048).
    """
    mol1, can1, err1 = _canonicalize(smiles1)
    if mol1 is None:
        return {"type": "similarity", "is_valid": False, "error": f"分子 1 解析失败：{err1}"}

    mol2, can2, err2 = _canonicalize(smiles2)
    if mol2 is None:
        return {"type": "similarity", "is_valid": False, "error": f"分子 2 解析失败：{err2}"}

    # Generate Morgan fingerprints
    fp_gen = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=n_bits)
    fp1 = fp_gen.GetFingerprint(mol1)
    fp2 = fp_gen.GetFingerprint(mol2)

    tanimoto = round(TanimotoSimilarity(fp1, fp2), 4)

    # Interpret similarity level
    if tanimoto >= 0.85:
        interpretation = "高度相似 (可能为同一化学系列)"
    elif tanimoto >= 0.7:
        interpretation = "中等相似 (结构有明显共性)"
    elif tanimoto >= 0.4:
        interpretation = "低度相似 (部分结构相关)"
    else:
        interpretation = "基本不相似 (结构差异显著)"

    return {
        "type": "similarity",
        "is_valid": True,
        "molecule_1": {
            "smiles": can1,
            "formula": rdMolDescriptors.CalcMolFormula(mol1),
            "heavy_atoms": mol1.GetNumHeavyAtoms(),
            "image": mol_to_png_b64(mol1),
        },
        "molecule_2": {
            "smiles": can2,
            "formula": rdMolDescriptors.CalcMolFormula(mol2),
            "heavy_atoms": mol2.GetNumHeavyAtoms(),
            "image": mol_to_png_b64(mol2),
        },
        "tanimoto": tanimoto,
        "interpretation": interpretation,
        "fingerprint_type": f"Morgan (ECFP{radius * 2})",
        "radius": radius,
        "n_bits": n_bits,
    }


# ── T5: Substructure Search (SMARTS + PAINS) ─────────────────────────────────


def substructure_match(smiles: str, smarts_pattern: str) -> dict:
    """Check if a SMARTS pattern matches a molecule, and run PAINS screening.

    Parameters
    ----------
    smiles        : Target molecule SMILES.
    smarts_pattern: SMARTS pattern to search for (e.g. functional group).
    """
    mol, canonical, error = _canonicalize(smiles)
    if mol is None:
        return {"type": "substructure", "is_valid": False, "error": error}

    # ── SMARTS matching ───────────────────────────────────────────────────
    pattern = Chem.MolFromSmarts(smarts_pattern.strip())
    if pattern is None:
        return {
            "type": "substructure",
            "is_valid": False,
            "error": f"无法解析 SMARTS 表达式：{smarts_pattern}",
        }

    matches = mol.GetSubstructMatches(pattern)
    matched = len(matches) > 0

    # Build highlighted image if matched
    if matched:
        flat_atoms = list({idx for match in matches for idx in match})
        highlighted_image = _mol_to_highlighted_png_b64(mol, flat_atoms)
    else:
        highlighted_image = mol_to_png_b64(mol)

    # ── PAINS screening ───────────────────────────────────────────────────
    pains_matches = []
    pains_entries = _PAINS_CATALOG.GetMatches(mol)
    for entry in pains_entries:
        pains_matches.append({
            "name": entry.GetDescription(),
        })

    return {
        "type": "substructure",
        "is_valid": True,
        "smiles": canonical,
        "smarts_pattern": smarts_pattern.strip(),
        "matched": matched,
        "match_count": len(matches),
        "match_atoms": [list(m) for m in matches],
        "highlighted_image": highlighted_image,
        "pains_alerts": pains_matches,
        "pains_clean": len(pains_matches) == 0,
    }


# ── T6: Murcko Scaffold Extraction ───────────────────────────────────────────


def murcko_scaffold(smiles: str) -> dict:
    """Extract the Bemis-Murcko scaffold and generic (carbon) scaffold.

    The Murcko scaffold preserves ring systems and linkers; the generic
    scaffold further reduces all atoms to carbon and all bonds to single.
    """
    mol, canonical, error = _canonicalize(smiles)
    if mol is None:
        return {"type": "scaffold", "is_valid": False, "error": error}

    try:
        scaffold = MurckoScaffold.GetScaffoldForMol(mol)
        scaffold_smiles = Chem.MolToSmiles(scaffold)
    except Exception as exc:
        return {
            "type": "scaffold",
            "is_valid": False,
            "error": f"骨架提取失败：{exc}",
        }

    try:
        generic = MurckoScaffold.MakeScaffoldGeneric(scaffold)
        generic_smiles = Chem.MolToSmiles(generic)
    except Exception:
        generic_smiles = ""

    return {
        "type": "scaffold",
        "is_valid": True,
        "smiles": canonical,
        "scaffold_smiles": scaffold_smiles,
        "generic_scaffold_smiles": generic_smiles,
        "molecule_image": mol_to_png_b64(mol),
        "scaffold_image": mol_to_png_b64(scaffold) if scaffold.GetNumAtoms() > 0 else "",
    }

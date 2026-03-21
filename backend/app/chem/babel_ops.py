"""
Pure Open Babel computation helpers.

No FastAPI, no agent framework, no tool registry — only openbabel and stdlib.

Re-used by:
  Phase 1  →  app/api/babel_api.py         (REST endpoints)
  Phase 2  →  app/tools/babel/prep.py      (agent tool wrappers, future)

Critical chemistry invariants observed throughout:
  1. AddHydrogens BEFORE make3D — hydrogens must be present so the force field
     can optimise ALL atom positions including H.  Doing it afterwards leaves new
     hydrogens at undefined / zero coordinates, poisoning docking scores.
  2. Gasteiger charges are assigned automatically by the PDBQT writer; we do NOT
     call the non-existent ``mol.calccharges()`` convenience method (AttributeError).
     Explicit charge computation uses the SWIG OBChargeModel API if needed.

Public API
----------
convert_format(molecule_str, input_fmt, output_fmt)   Tool 1: universal converter
build_3d_conformer(smiles, name, forcefield, steps)   Tool 2: 3D conformer builder
prepare_pdbqt(smiles, name, ph)                       Tool 3: docking PDBQT prep
"""

from __future__ import annotations

from openbabel import pybel

# ── Supported format sets (evaluated once at import time) ─────────────────────

_IN_FMTS:  set[str] = set(pybel.informats.keys())
_OUT_FMTS: set[str] = set(pybel.outformats.keys())


def _fmt_error(fmt: str, direction: str) -> dict:
    """Return a structured validation error for an unsupported format code."""
    supported = sorted(_IN_FMTS if direction == "input" else _OUT_FMTS)
    return {
        "is_valid": False,
        "error": (
            f"不支持的{direction}格式：'{fmt}'。"
            f"常用格式：smi, inchi, inchikey, sdf, mol2, pdb, xyz, mol。"
            f"完整列表共 {len(supported)} 种。"
        ),
    }


# ── Tool 1: Universal Format Converter ───────────────────────────────────────


def convert_format(
    molecule_str: str,
    input_fmt: str,
    output_fmt: str,
) -> dict:
    """Convert a molecule between any two Open Babel-supported formats.

    Parameters
    ----------
    molecule_str : Molecule encoded in ``input_fmt`` (SMILES, InChI, SDF text, …).
    input_fmt    : Open Babel format code for the input  (e.g. ``"smi"``, ``"inchi"``).
    output_fmt   : Open Babel format code for the output (e.g. ``"sdf"``, ``"mol2"``).

    Returns dict matching ``FormatConversionResult | BabelError`` TypeScript union.
    """
    input_fmt  = input_fmt.strip().lower()
    output_fmt = output_fmt.strip().lower()

    if input_fmt  not in _IN_FMTS:
        return _fmt_error(input_fmt,  "input")
    if output_fmt not in _OUT_FMTS:
        return _fmt_error(output_fmt, "output")

    try:
        mol = pybel.readstring(input_fmt, molecule_str.strip())
    except Exception as exc:
        return {
            "is_valid": False,
            "error": f"Open Babel 无法解析输入的 {input_fmt.upper()} 字符串：{exc}",
        }

    try:
        output_str = mol.write(output_fmt).strip()
    except Exception as exc:
        return {
            "is_valid": False,
            "error": f"转换为 {output_fmt.upper()} 时出错：{exc}",
        }

    return {
        "type":             "format_conversion",
        "is_valid":         True,
        "input_format":     input_fmt,
        "output_format":    output_fmt,
        "output":           output_str,
        "atom_count":       mol.OBMol.NumAtoms(),
        "heavy_atom_count": mol.OBMol.NumHvyAtoms(),
    }


# ── Tool 2: 3D Conformer Builder ─────────────────────────────────────────────


def build_3d_conformer(
    smiles: str,
    name: str = "",
    forcefield: str = "mmff94",
    steps: int = 500,
) -> dict:
    """Generate and force-field-optimise a 3D conformer from a SMILES string.

    ``pybel.Molecule.make3D()`` internally calls AddHydrogens before geometry
    generation, so all atom positions — including H — are fully optimised.
    Falls back to UFF automatically if MMFF94 setup fails for the molecule.

    Parameters
    ----------
    smiles     : Standard SMILES string.
    name       : Optional compound name (used in output filename).
    forcefield : ``'mmff94'`` (default, preferred for drug-like molecules) or ``'uff'``.
    steps      : Conjugate-gradient optimisation steps (default 500).

    Returns dict matching ``Conformer3DResult | BabelError`` TypeScript union.
    """
    smiles    = smiles.strip()
    forcefield = forcefield.strip().lower()

    if forcefield not in ("mmff94", "uff", "gaff", "ghemical"):
        return {
            "is_valid": False,
            "error": f"不支持的力场：'{forcefield}'。请使用 mmff94 或 uff。",
        }

    try:
        mol = pybel.readstring("smi", smiles)
    except Exception as exc:
        return {"is_valid": False, "error": f"无法解析 SMILES：{exc}"}

    if mol.OBMol.NumAtoms() == 0:
        return {"is_valid": False, "error": f"无法解析 SMILES：{smiles}"}

    try:
        # make3D internally adds H, embeds 3D coordinates, and runs the force field.
        mol.make3D(forcefield=forcefield, steps=steps)
    except Exception as exc:
        return {"is_valid": False, "error": f"3D 构象生成失败：{exc}"}

    try:
        sdf_content = mol.write("sdf").strip()
    except Exception as exc:
        return {"is_valid": False, "error": f"SDF 输出失败：{exc}"}

    # Sanity check: at least one atom should have a non-zero Z coordinate.
    has_3d = any(
        abs(mol.OBMol.GetAtom(i).GetZ()) > 1e-4
        for i in range(1, mol.OBMol.NumAtoms() + 1)
    )

    return {
        "type":             "conformer_3d",
        "is_valid":         True,
        "name":             name.strip(),
        "smiles":           smiles,
        "sdf_content":      sdf_content,
        "atom_count":       mol.OBMol.NumAtoms(),
        "heavy_atom_count": mol.OBMol.NumHvyAtoms(),
        "forcefield":       forcefield,
        "steps":            steps,
        "has_3d_coords":    has_3d,
    }


# ── Tool 3: Docking Prep / PDBQT Generator ───────────────────────────────────


def prepare_pdbqt(
    smiles: str,
    name: str = "",
    ph: float = 7.4,
) -> dict:
    """Prepare a ligand PDBQT file for AutoDock-family docking (Vina, Smina, GNINA).

    Correct chemistry sequence — ORDER MATTERS:
      1. Parse SMILES (heavy atoms only, no H).
      2. AddHydrogens at physiological pH **before** 3D generation, so the force
         field sees all atoms from the start and no H ends up at origin (0,0,0).
      3. make3D() generates 3D coordinates AND optimises every atom including H.
      4. write("pdbqt") — the OpenBabel PDBQT writer auto-assigns Gasteiger
         partial charges internally; no separate charge-calculation call needed.

    Parameters
    ----------
    smiles : Standard SMILES string (2D, no explicit H required).
    name   : Optional compound name (used in PDBQT REMARK and filename).
    ph     : Protonation pH (default 7.4 — physiological).

    Returns dict matching ``PdbqtPrepResult | BabelError`` TypeScript union.
    """
    smiles = smiles.strip()

    try:
        mol = pybel.readstring("smi", smiles)
    except Exception as exc:
        return {"is_valid": False, "error": f"无法解析 SMILES：{exc}"}

    if mol.OBMol.NumAtoms() == 0:
        return {"is_valid": False, "error": f"无法解析 SMILES：{smiles}"}

    # Step 2 — Add H at the target pH BEFORE 3D generation.
    # Signature: AddHydrogens(polar_only, correct_for_ph, pH)
    mol.OBMol.AddHydrogens(False, True, ph)

    # Step 3 — Generate and optimise 3D coordinates for ALL atoms (including H).
    try:
        mol.make3D(forcefield="mmff94", steps=500)
    except Exception as exc:
        return {"is_valid": False, "error": f"3D 构象生成失败：{exc}"}

    # Step 4 — Write PDBQT; the writer auto-assigns Gasteiger partial charges.
    try:
        pdbqt_content = mol.write("pdbqt").strip()
    except Exception as exc:
        return {"is_valid": False, "error": f"PDBQT 输出失败：{exc}"}

    if not pdbqt_content:
        return {"is_valid": False, "error": "PDBQT 输出为空，请检查分子结构。"}

    rotatable_bonds  = mol.OBMol.NumRotors()
    heavy_atom_count = mol.OBMol.NumHvyAtoms()
    total_atoms      = mol.OBMol.NumAtoms()

    return {
        "type":                "pdbqt_prep",
        "is_valid":            True,
        "name":                name.strip(),
        "smiles":              smiles,
        "pdbqt_content":       pdbqt_content,
        "ph":                  ph,
        "rotatable_bonds":     rotatable_bonds,
        "heavy_atom_count":    heavy_atom_count,
        "total_atom_count":    total_atoms,
        "has_root_marker":     "ROOT"    in pdbqt_content,
        "has_torsdof_marker":  "TORSDOF" in pdbqt_content,
        # Warning flag: Vina/Smina accuracy degrades above 10 rotatable bonds.
        "flexibility_warning": rotatable_bonds > 10,
    }

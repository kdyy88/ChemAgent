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
compute_mol_properties(smiles)                        T7: molecular properties
list_supported_formats()                              Utility: format enumeration
"""

from __future__ import annotations

import io
import zipfile

from openbabel import openbabel, pybel

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

    # ── Extract force-field energy after optimisation ─────────────────────
    energy_kcal_mol: float | None = None
    try:
        ff = pybel._forcefields[forcefield]
        if ff.Setup(mol.OBMol):
            energy_kcal_mol = round(ff.Energy(), 4)
    except Exception:
        pass  # energy is optional — don't fail the whole tool

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
        "energy_kcal_mol":  energy_kcal_mol,
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


# ── T7: Molecular Properties (OpenBabel) ─────────────────────────────────────


def compute_mol_properties(smiles: str) -> dict:
    """Compute core molecular properties using OpenBabel.

    Returns formula, exact mass, formal charge, spin multiplicity, and atom counts.
    """
    smiles = smiles.strip()
    try:
        mol = pybel.readstring("smi", smiles)
    except Exception as exc:
        return {"type": "mol_properties", "is_valid": False, "error": f"无法解析 SMILES：{exc}"}

    if mol.OBMol.NumAtoms() == 0:
        return {"type": "mol_properties", "is_valid": False, "error": f"无法解析 SMILES：{smiles}"}

    obmol = mol.OBMol
    return {
        "type": "mol_properties",
        "is_valid": True,
        "smiles": smiles,
        "formula": mol.formula,
        "exact_mass": round(obmol.GetExactMass(), 4),
        "molecular_weight": round(obmol.GetMolWt(), 4),
        "formal_charge": obmol.GetTotalCharge(),
        "spin_multiplicity": obmol.GetTotalSpinMultiplicity(),
        "heavy_atom_count": obmol.NumHvyAtoms(),
        "atom_count": obmol.NumAtoms(),
        "bond_count": obmol.NumBonds(),
        "rotatable_bonds": obmol.NumRotors(),
    }


# ── Utility: Supported Format Listing ─────────────────────────────────────────


def list_supported_formats() -> dict:
    """List all OpenBabel-supported input and output formats.

    Returns sorted lists with format code + description for each direction.
    """
    input_formats = [
        {"code": code, "description": desc}
        for code, desc in sorted(pybel.informats.items())
    ]
    output_formats = [
        {"code": code, "description": desc}
        for code, desc in sorted(pybel.outformats.items())
    ]
    return {
        "input_formats": input_formats,
        "output_formats": output_formats,
        "input_count": len(input_formats),
        "output_count": len(output_formats),
    }


# ── F2: Partial Charge Analysis ───────────────────────────────────────────────

_CHARGE_METHODS = {"gasteiger", "mmff94", "qeq", "eem"}

# OBElementTable is removed in newer OpenBabel builds; use a static lookup.
_ATOMIC_SYMBOL: dict[int, str] = {
    1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O",
    9: "F", 10: "Ne", 11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P",
    16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca", 26: "Fe", 29: "Cu",
    30: "Zn", 33: "As", 34: "Se", 35: "Br", 53: "I",
}


def compute_partial_charges(smiles: str, method: str = "gasteiger") -> dict:
    """Compute per-atom partial charges using the specified charge model.

    Parameters
    ----------
    smiles : Standard SMILES string.
    method : Charge model — 'gasteiger' (default), 'mmff94', 'qeq', or 'eem'.

    Returns dict matching ``PartialChargeResult | BabelError`` TypeScript union.
    """
    smiles = smiles.strip()
    method = method.strip().lower()

    if method not in _CHARGE_METHODS:
        return {
            "type": "partial_charge",
            "is_valid": False,
            "error": f"不支持的电荷模型：'{method}'。可选：gasteiger, mmff94, qeq, eem",
        }

    try:
        mol = pybel.readstring("smi", smiles)
    except Exception as exc:
        return {"type": "partial_charge", "is_valid": False, "error": f"无法解析 SMILES：{exc}"}

    if mol.OBMol.NumAtoms() == 0:
        return {"type": "partial_charge", "is_valid": False, "error": f"无法解析 SMILES：{smiles}"}

    # Add hydrogens so charge distribution is physically meaningful
    mol.OBMol.AddHydrogens()

    # Compute charges via OBChargeModel
    charge_model = openbabel.OBChargeModel.FindType(method)
    if charge_model is None:
        return {
            "type": "partial_charge",
            "is_valid": False,
            "error": f"OpenBabel 未找到电荷模型 '{method}'，可能未编译支持。",
        }

    success = charge_model.ComputeCharges(mol.OBMol)
    if not success:
        return {
            "type": "partial_charge",
            "is_valid": False,
            "error": f"电荷计算失败 (模型: {method})。",
        }

    partial_charges = charge_model.GetPartialCharges()

    atoms = []
    for i in range(mol.OBMol.NumAtoms()):
        ob_atom = mol.OBMol.GetAtom(i + 1)  # OBMol is 1-indexed
        atomic_num = ob_atom.GetAtomicNum()
        atoms.append({
            "idx": i,
            "element": _ATOMIC_SYMBOL.get(atomic_num, f"#{atomic_num}"),
            "charge": round(partial_charges[i], 4) if i < len(partial_charges) else 0.0,
        })

    # Only return heavy atoms in the summary
    heavy_atoms = [a for a in atoms if a["element"] != "H"]

    return {
        "type": "partial_charge",
        "is_valid": True,
        "smiles": smiles,
        "charge_model": method,
        "atoms": atoms,
        "heavy_atoms": heavy_atoms,
        "total_charge": round(sum(a["charge"] for a in atoms), 4),
        "atom_count": len(atoms),
        "heavy_atom_count": len(heavy_atoms),
    }


# ── F3: SDF Batch Processing (Split / Merge) ─────────────────────────────────


def sdf_split(sdf_content: str) -> dict:
    """Split a multi-molecule SDF file into individual molecules.

    Returns a dict with a list of molecule entries (SMILES + name) and
    a ZIP archive (in-memory bytes) containing individual SDF files.
    """
    molecules = []
    zip_buffer = io.BytesIO()

    # Split by the $$$$ delimiter (standard SDF separator)
    blocks = sdf_content.strip().split("$$$$")
    blocks = [b.strip() for b in blocks if b.strip()]

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, block in enumerate(blocks):
            sdf_text = block + "\n$$$$\n"
            try:
                mol = pybel.readstring("sdf", sdf_text)
                mol_name = mol.title.strip() or f"molecule_{i + 1}"
                mol_smiles = mol.write("smi").strip().split("\t")[0]
            except Exception:
                mol_name = f"molecule_{i + 1}"
                mol_smiles = "parse_error"

            molecules.append({
                "index": i,
                "name": mol_name,
                "smiles": mol_smiles,
            })

            filename = f"{mol_name}.sdf"
            # De-duplicate filenames
            zf.writestr(f"{i + 1:04d}_{filename}", sdf_text)

    return {
        "type": "sdf_split",
        "is_valid": True,
        "molecule_count": len(molecules),
        "molecules": molecules[:100],  # cap preview at 100
        "zip_bytes": zip_buffer.getvalue(),
    }


def sdf_merge(sdf_contents: list[str]) -> dict:
    """Merge multiple SDF file contents into a single SDF file.

    Parameters
    ----------
    sdf_contents : List of SDF file content strings.
    """
    merged_blocks: list[str] = []
    total_mols = 0
    errors = 0

    for content in sdf_contents:
        blocks = content.strip().split("$$$$")
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            try:
                mol = pybel.readstring("sdf", block + "\n$$$$\n")
                merged_blocks.append(mol.write("sdf").strip())
                total_mols += 1
            except Exception:
                errors += 1

    merged_sdf = "\n".join(merged_blocks)

    return {
        "type": "sdf_merge",
        "is_valid": True,
        "molecule_count": total_mols,
        "error_count": errors,
        "sdf_content": merged_sdf,
    }

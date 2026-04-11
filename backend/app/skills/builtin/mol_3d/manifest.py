"""
mol_3d built-in skill manifest.

Activates Open Babel 3D computation tools:
  - Format conversion (SMILES ↔ SDF ↔ MOL2 ↔ PDB ↔ 110+ formats)
  - 3D conformer generation with MMFF94/UFF force field
  - Docking preparation (PDBQT with pH-corrected protonation)
  - Molecular property calculation
  - Partial charge computation (Gasteiger, MMFF94, QEq, EEM)
"""
from __future__ import annotations

from app.skills.base import SkillManifest
from app.tools.registry import ToolPermission

manifest = SkillManifest(
    name="mol_3d",
    display_name="3D 构象与分子对接准备",
    description=(
        "三维构象生成技能：格式转换、MMFF94/UFF 力场优化、PDBQT 配体准备、"
        "分子性质计算、原子部分电荷计算。用于对接前处理流程。"
    ),
    tool_names=[
        "tool_convert_format",
        "tool_build_3d_conformer",
        "tool_prepare_pdbqt",
        "tool_compute_mol_properties",
        "tool_compute_partial_charges",
        "tool_list_formats",
        "tool_ask_human",
        "tool_update_task_status",
    ],
    prompt_fragment=(
        "【3D 构象技能已激活】\n"
        "你可以使用 Open Babel 工具生成三维构象、准备 PDBQT 对接文件、执行格式转换。"
        "生成 3D 构象前请确认使用干净、有效的 SMILES。"
    ),
    permission_required=ToolPermission.COMPUTE,
    enabled_by_default=True,
)

# Self-register on import
from app.skills.loader import register_skill
register_skill(manifest)

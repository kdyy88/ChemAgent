"""
rdkit_analysis built-in skill manifest.

Activates all core RDKit analysis and visualization tools:
  - SMILES validation & canonicalization
  - Molecular descriptors (Lipinski, QED, TPSA, SA Score)
  - Tanimoto similarity
  - Substructure matching + PAINS screening
  - Murcko scaffold extraction
  - Salt stripping & neutralization
  - 2D structure rendering
  - PubChem compound lookup
  - Web/literature search
  - HITL clarification + task status (system tools always included)
"""
from __future__ import annotations

from app.skills.base import SkillManifest
from app.tools.registry import ToolPermission

manifest = SkillManifest(
    name="rdkit_analysis",
    display_name="RDKit 化学分析",
    description=(
        "核心化学分析技能：SMILES 校验、分子描述符（Lipinski/QED/TPSA）、"
        "相似度计算、子结构匹配、Murcko Scaffold 提取、盐脱除、2D 结构图渲染。"
    ),
    tool_names=[
        "tool_validate_smiles",
        "tool_compute_descriptors",
        "tool_compute_similarity",
        "tool_substructure_match",
        "tool_murcko_scaffold",
        "tool_strip_salts",
        "tool_render_smiles",
        "tool_pubchem_lookup",
        "tool_web_search",
        "tool_ask_human",
        "tool_update_task_status",
    ],
    prompt_fragment=(
        "【RDKit 分析技能已激活】\n"
        "你可以使用 RDKit 工具进行完整的小分子化学分析，包括描述符计算、相似度、子结构匹配等。"
    ),
    permission_required=ToolPermission.READONLY,
    enabled_by_default=True,
)

# Self-register on import
from app.skills.loader import register_skill
register_skill(manifest)

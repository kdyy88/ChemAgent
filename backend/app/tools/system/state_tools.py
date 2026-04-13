"""State Management Tools -- ChemAgent System Layer
====================================================

Four tools that let the LLM explicitly write to the three stateful domains
of ``ChemState`` that have no automatic harvest path:

  tool_update_scratchpad    -- append rules / failures / update research goal
  tool_create_molecule_node -- register a molecule branch with explicit lineage
  tool_update_viewport      -- set exactly which molecules are in focus
  tool_patch_diagnostics    -- write computed properties into molecule_tree[mol_*].diagnostics

All three communicate through the ``__chem_protocol__`` mechanism (Phase 3).
The executor detects the marker, applies the payload to ChemState, and strips
the marker before the message reaches the LLM's context window.

Protocol types emitted
----------------------
- ``ScratchpadUpdate`` → executor merges lists into ``ChemState.scratchpad``
- ``NodeCreate``       → executor upserts a node in ``ChemState.molecule_tree``
                         and appends the id to ``ChemState.viewport``
- ``ViewportUpdate``   → executor replaces ``ChemState.viewport`` precisely

Design principle
----------------
These tools are *pure state operations* -- no filesystem I/O, no network, no
subprocesses.  They are rated L1 (safe for sub-agents, no approval gate).
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from langchain_core.tools import tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _artifact_id_from_smiles(canonical_smiles: str) -> str:
    """Stable artifact ID from canonical SMILES -- mirrors executor.py convention."""
    return "mol_" + hashlib.md5(canonical_smiles.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# tool_update_scratchpad
# ---------------------------------------------------------------------------


@tool
def tool_update_scratchpad(
    established_rules: Annotated[
        list[str],
        "通过实验/计算归纳出的化学规律，将被追加到黑板现有规则列表（例如 ['C=CC(=O)N warhead 必须保留', 'LogP > 5 降低透膜性']）",
    ] = [],
    failed_attempts: Annotated[
        list[str],
        "已验证失败的路径，防止重复踩坑，将被追加到黑板现有失败记录（例如 ['Bioisostere A 对 BTK C481 亲和力弱于母本']）",
    ] = [],
    research_goal: Annotated[
        str,
        "（可选）更新或设置本次会话的研究总目标；留空则不修改现有目标",
    ] = "",
) -> str:
    """Write chemical insights, constraints, and failures to the persistent scratchpad.

    The executor merges new entries **on top of** the existing scratchpad state
    via the ``merge_scratchpad`` logic -- existing rules are never deleted.

    Call this tool:
    - At the START of work when the user specifies hard constraints
      (e.g. ''keep acrylamide warhead'', ''must contain fused indole'').
    - After any tool confirms a rule (substructure match, property threshold).
    - After any experiment confirms a failure path.
    """
    if not established_rules and not failed_attempts and not research_goal.strip():
        return json.dumps(
            {"is_valid": False, "error": "所有参数均为空，无需写入黑板。"},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "__chem_protocol__": "ScratchpadUpdate",
            "established_rules": [str(r).strip() for r in established_rules if str(r).strip()],
            "failed_attempts": [str(f).strip() for f in failed_attempts if str(f).strip()],
            "research_goal": research_goal.strip(),
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# tool_create_molecule_node
# ---------------------------------------------------------------------------


@tool
def tool_create_molecule_node(
    smiles: Annotated[
        str,
        "分子的 canonical SMILES（建议先用 tool_validate_smiles 获取规范化字符串）",
    ],
    parent_id: Annotated[
        str,
        "母本分子的 artifact_id（例如 'mol_a49f7510'）；如果是首个分子则留空",
    ] = "",
    creation_operation: Annotated[
        str,
        "生成操作的描述（例如 'scaffold_hop_to_pyrrolopyrimidine'、'fragment_growing'）；用于渲染演化树",
    ] = "",
    status: Annotated[
        str,
        "初始状态：staged（参考母本或待评估）| exploring（主动探索中）| lead（已通过属性筛选的候选）| rejected（已排除）。"
        "注意：参考母本/起始物请用 staged；status=\"lead\" 专属于经过 tool_screen_molecules 筛选后留下的分子，不要在注册阶段手动指定。",
    ] = "staged",
    aliases: Annotated[
        list[str],
        "可选：化合物别名或编号（例如 ['Hop-1', 'CAS 12345-67-8']）",
    ] = [],
) -> str:
    """Register a new molecule or annotate an existing one with explicit lineage.

    This is the canonical way to build the ``molecule_tree`` branching graph.
    Unlike the auto-harvest (which only fires for a fixed set of tools and
    never knows the parent), this tool lets the LLM explicitly declare:

       "node B was created from node A by scaffold_hop_to_indole"

    The executor upserts the node (preserving any existing diagnostics) and
    adds its artifact_id to ``viewport.focused_artifact_ids`` so the frontend
    renders it immediately.

    **When to call this tool:**
    - Right after designing a new molecule (before or after 2D/3D generation).
    - When you want to annotate an auto-harvested node with parent_id and
      creation_operation (the node already exists; this just enriches it).
    """
    smiles = smiles.strip()
    if not smiles:
        return json.dumps(
            {"is_valid": False, "error": "smiles 不能为空。"},
            ensure_ascii=False,
        )

    artifact_id = _artifact_id_from_smiles(smiles)

    return json.dumps(
        {
            "__chem_protocol__": "NodeCreate",
            "artifact_id": artifact_id,
            "smiles": smiles,
            "parent_id": parent_id.strip() or None,
            "creation_operation": creation_operation.strip() or None,
            "status": status.strip() or "staged",
            "aliases": [str(a).strip() for a in aliases if str(a).strip()],
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# tool_update_viewport
# ---------------------------------------------------------------------------


@tool
def tool_update_viewport(
    focused_artifact_ids: Annotated[
        list[str],
        "要在前端分屏对比的 artifact_id 列表（例如 ['mol_a49f7510', 'mol_c6afbf3c']）",
    ],
    reference_artifact_id: Annotated[
        str,
        "（可选）对比时的参考母本 artifact_id；前端通常高亮显示",
    ] = "",
) -> str:
    """Explicitly switch the IDE molecular viewport to a set of molecules.

    Call this tool **as soon as** you have designed or identified the molecules
    you want to compare -- do **not** wait for 3D conformer generation.  The
    frontend renders the split view immediately from artifact IDs; it does not
    need 3D coordinates to show the 2D comparison panel.

    The viewport state is **replaced** (not appended) by this call.  To keep
    previously focused molecules, include their IDs in ``focused_artifact_ids``.
    """
    ids = list(dict.fromkeys(str(i).strip() for i in focused_artifact_ids if str(i).strip()))
    if not ids:
        return json.dumps(
            {"is_valid": False, "error": "focused_artifact_ids 不能为空列表。"},
            ensure_ascii=False,
        )

    ref = reference_artifact_id.strip() or None

    return json.dumps(
        {
            "__chem_protocol__": "ViewportUpdate",
            "focused_artifact_ids": ids,
            "reference_artifact_id": ref,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# tool_patch_diagnostics
# ---------------------------------------------------------------------------


@tool
def tool_patch_diagnostics(
    updates: Annotated[
        list[dict],
        """
        每项格式：{"artifact_id": "mol_*", "diagnostics": {"tpsa": 78.3, "logp": 4.64, ...}}
        - artifact_id：molecule_tree 中已存在的节点 ID（如 mol_ca3086eb）。
        - diagnostics：任意数值或字符串型属性均可写入，无需预先声明；与现有字段合并（不清空其他字段）。
        适用场景：tool_run_shell Python 脚本、子代理、外部数据库等任何来源的计算结果。
        """,
    ],
) -> str:
    """Explicitly write computed property values into molecule_tree[mol_*].diagnostics.

    This is the **escape hatch** for any property calculation that does NOT go
    through a native chemistry tool (tool_compute_descriptors, tool_evaluate_molecule
    etc.).  Native tools auto-patch diagnostics; everything else should call
    this tool to keep molecule_tree in sync so that tool_screen_molecules and
    the IDE viewport table always reflect up-to-date values.

    **When to call this tool:**
    - After tool_run_shell computed tPSA / LogP via RDKit Python.
    - After a sub-agent returned property data in its completion dict.
    - After importing data from an external database (IC50, solubility, etc.).

    **When NOT to call this tool:**
    - After tool_compute_descriptors / tool_evaluate_molecule / tool_compute_similarity
      — those auto-patch diagnostics through the DIAGNOSTIC_SCHEMA pipeline.

    The node status is NOT changed by this tool.  Call tool_screen_molecules
    afterwards to converge statuses based on updated diagnostics.
    """
    cleaned: list[dict] = []
    for upd in (updates or []):
        aid = str(upd.get("artifact_id") or "").strip()
        diag = {k: v for k, v in (upd.get("diagnostics") or {}).items()}
        if aid and diag:
            cleaned.append({"artifact_id": aid, "diagnostics": diag})

    if not cleaned:
        return json.dumps(
            {"is_valid": False, "error": "updates 为空或每项均缺少 artifact_id / diagnostics 字段。"},
            ensure_ascii=False,
        )

    return json.dumps(
        {"__chem_protocol__": "BatchNodeUpdate", "updates": cleaned},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Tool list for catalog registration
# ---------------------------------------------------------------------------

ALL_STATE_TOOLS = [
    tool_update_scratchpad,
    tool_create_molecule_node,
    tool_update_viewport,
    tool_patch_diagnostics,
]
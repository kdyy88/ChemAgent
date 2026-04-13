"""Molecule screening tool — batch status convergence via property criteria.

``tool_screen_molecules`` reads node diagnostics directly from the live
``molecule_tree`` snapshot (injected by the executor via configurable) and
emits a ``BatchNodeUpdate`` protocol payload that the executor applies in one
atomic pass.

Design goals
------------
- **Zero per-tool code** — new screening dimensions only require calling this
  tool with updated criteria; no code changes needed.
- **Executor-injected context** — same pattern as ``tool_edit_file`` receiving
  ``read_file_state`` via ``config.configurable``.
- **Idempotent** — running the same criteria twice produces the same result.
- **Transparent** — the tool returns a human-readable summary alongside the
  protocol payload so the LLM can narrate the result to the user.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


# ---------------------------------------------------------------------------
# Criteria evaluation
# ---------------------------------------------------------------------------

def _evaluate_criteria(
    diagnostics: dict[str, Any],
    criteria: dict[str, dict[str, float]],
) -> str | None:
    """Return 'pass' / 'fail' / None (skip — missing data for all criteria keys).

    A node 'passes' only if ALL criteria with available data are satisfied.
    If the node has no diagnostic data at all for any criterion, return None
    (skip — don't change its status).
    """
    any_data = False
    for key, bounds in criteria.items():
        if key not in diagnostics:
            continue
        any_data = True
        val = diagnostics[key]
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if "min" in bounds and fval < float(bounds["min"]):
            return "fail"
        if "max" in bounds and fval > float(bounds["max"]):
            return "fail"
    return "pass" if any_data else None


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool
def tool_screen_molecules(
    criteria: Annotated[
        dict,
        """
        属性筛选条件，格式：
        {
          "tpsa": {"max": 70},
          "logp": {"min": 3, "max": 5},
          "mw":   {"max": 550},
          "qed":  {"min": 0.5}
        }
        支持的边界键：min（下限，含）、max（上限，含）。
        只有在 diagnostics 中已存在对应字段的节点才参与筛选；缺少全部字段的节点
        被跳过（状态不变）。
        满足所有可用标准 → lead_status；违反任一标准 → reject_status。
        """,
    ],
    lead_status: Annotated[
        str,
        "通过所有条件时赋予的状态标签，默认 'lead'",
    ] = "lead",
    reject_status: Annotated[
        str,
        "违反任一条件时赋予的状态标签，默认 'rejected'",
    ] = "rejected",
    scope_status: Annotated[
        str,
        "只筛选此状态的节点；留空则筛选 molecule_tree 中的所有节点",
    ] = "exploring",
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """Screen molecule_tree nodes by property thresholds and batch-update their status.

    The executor injects the current ``molecule_tree`` snapshot before this
    tool runs, so it always sees the freshest diagnostics written by
    ``tool_compute_descriptors`` or other property tools in the same turn.

    **When to call this tool:**
    - After computing properties (tPSA, LogP, QED etc.) for a set of candidates.
    - When you want to converge the ``molecule_tree`` statuses so the IDE
      viewport and downstream tools only see confirmed leads.

    **Typical workflow:**
    1. ``tool_create_molecule_node`` × N  → register candidates in tree
    2. ``tool_compute_descriptors`` × N   → auto-patches diagnostics via DIAGNOSTIC_SCHEMA
    3. ``tool_screen_molecules``          → batch-set lead / rejected statuses
    4. ``tool_update_viewport``           → focus only on lead nodes
    """
    configurable: dict = (config or {}).get("configurable") or {}  # type: ignore[union-attr]
    tree: dict[str, Any] = dict(configurable.get("molecule_tree") or {})

    if not tree:
        return json.dumps(
            {"is_valid": False, "error": "molecule_tree 为空或未注入；请先调用 tool_create_molecule_node 注册分子节点。"},
            ensure_ascii=False,
        )
    if not criteria:
        return json.dumps(
            {"is_valid": False, "error": "criteria 不能为空。"},
            ensure_ascii=False,
        )

    updates: list[dict] = []
    skipped: list[str] = []
    leads: list[str] = []
    rejected: list[str] = []

    for aid, node in tree.items():
        node_status = str(node.get("status") or "")
        if scope_status and node_status != scope_status:
            continue

        diag: dict[str, Any] = dict(node.get("diagnostics") or {})
        verdict = _evaluate_criteria(diag, criteria)

        if verdict is None:
            skipped.append(aid)
            continue

        new_status = lead_status if verdict == "pass" else reject_status
        updates.append({"artifact_id": aid, "status": new_status})
        (leads if verdict == "pass" else rejected).append(aid)

    summary = (
        f"筛选完成：{len(leads)} 个 lead，{len(rejected)} 个 rejected，"
        f"{len(skipped)} 个因缺少 diagnostics 数据而跳过。"
        + (f"\nLead 节点: {leads}" if leads else "")
        + (f"\nRejected 节点: {rejected}" if rejected else "")
    )

    return json.dumps(
        {
            "__chem_protocol__": "BatchNodeUpdate",
            "updates": updates,
            "summary": summary,
            "lead_count": len(leads),
            "rejected_count": len(rejected),
            "skipped_count": len(skipped),
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Export list
# ---------------------------------------------------------------------------

ALL_SCREEN_TOOLS = [tool_screen_molecules]

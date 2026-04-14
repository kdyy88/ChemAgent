"""Molecule screening tool -- class-based BaseChemTool contract."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.domain.schemas.workflow import ValidationResult
from app.tools.base import ChemStateTool, _current_tool_config


# ---------------------------------------------------------------------------
# Criteria evaluation helper (module-level, preserved from original)
# ---------------------------------------------------------------------------


def _evaluate_criteria(
    diagnostics: dict[str, Any],
    criteria: dict[str, dict[str, float]],
) -> str | None:
    """Return 'pass' / 'fail' / None (skip -- missing data for all criteria keys)."""
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
# ToolScreenMolecules
# ---------------------------------------------------------------------------


class ScreenMoleculesInput(BaseModel):
    criteria: dict = Field(
        description=(
            '属性筛选条件，格式：{"tpsa": {"max": 70}, "logp": {"min": 3, "max": 5}, ...}. '
            "支持的边界键：min（下限，含）、max（上限，含）。"
        )
    )
    lead_status: str = Field(default="lead", description="通过所有条件时赋予的状态标签")
    reject_status: str = Field(default="rejected", description="违反任一条件时赋予的状态标签")
    scope_status: str = Field(
        default="exploring",
        description="只筛选此状态的节点；留空则筛选所有节点",
    )


class ToolScreenMolecules(ChemStateTool[ScreenMoleculesInput, str]):
    """Screen molecule_tree nodes by property thresholds and batch-update their status.

    The tool reads the current ``molecule_tree`` snapshot from LangGraph
    configurable context and emits a ``BatchNodeUpdate`` protocol payload that
    the executor applies atomically.
    """

    name = "tool_screen_molecules"
    args_schema = ScreenMoleculesInput
    tier = "L1"
    max_result_size_chars = 4_000

    async def validate_input(
        self, args: ScreenMoleculesInput, context: dict
    ) -> ValidationResult:
        if not args.criteria:
            return ValidationResult(result=False, message="criteria 不能为空。")
        return ValidationResult(result=True)

    def call(self, args: ScreenMoleculesInput) -> str:
        """Filter molecules in the workspace by property criteria and promote leads or reject candidates."""
        config = _current_tool_config.get()
        configurable: dict = ((config or {}).get("configurable") or {})
        tree: dict[str, Any] = dict(configurable.get("molecule_tree") or {})

        if not tree:
            return json.dumps(
                {
                    "is_valid": False,
                    "error": (
                        "molecule_tree 为空或未注入；"
                        "请先调用 tool_create_molecule_node 注册分子节点。"
                    ),
                },
                ensure_ascii=False,
            )

        updates: list[dict] = []
        skipped: list[str] = []
        leads: list[str] = []
        rejected: list[str] = []

        for aid, node in tree.items():
            node_status = str(node.get("status") or "")
            if args.scope_status and node_status != args.scope_status:
                continue

            diag: dict[str, Any] = dict(node.get("diagnostics") or {})
            verdict = _evaluate_criteria(diag, args.criteria)

            if verdict is None:
                skipped.append(aid)
                continue

            new_status = args.lead_status if verdict == "pass" else args.reject_status
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


tool_screen_molecules = ToolScreenMolecules().as_langchain_tool()

ALL_SCREEN_TOOLS = [tool_screen_molecules]



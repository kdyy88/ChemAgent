"""State Management Tools -- class-based BaseChemTool contract.

Four tools that let the LLM explicitly write to ChemState domains:
  ToolUpdateScratchpad    -- append rules / failures / update research goal
  ToolCreateMoleculeNode  -- register a molecule branch with explicit lineage
  ToolUpdateViewport      -- set exactly which molecules are in focus
  ToolPatchDiagnostics    -- write computed properties into molecule_tree diagnostics
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field

from app.domain.schemas.workflow import ValidationResult
from app.tools.base import ChemStateTool


def _artifact_id_from_smiles(canonical_smiles: str) -> str:
    return "mol_" + hashlib.md5(canonical_smiles.encode()).hexdigest()[:8]


# ── 1. tool_update_scratchpad ─────────────────────────────────────────────────


class UpdateScratchpadInput(BaseModel):
    established_rules: list[str] = Field(
        default_factory=list,
        description="通过实验/计算归纳出的化学规律，将被追加到黑板现有规则列表",
    )
    failed_attempts: list[str] = Field(
        default_factory=list,
        description="已验证失败的路径，防止重复踩坑，将被追加到黑板现有失败记录",
    )
    research_goal: str = Field(
        default="",
        description="（可选）更新或设置本次会话的研究总目标；留空则不修改现有目标",
    )


class ToolUpdateScratchpad(ChemStateTool[UpdateScratchpadInput, str]):
    """Write chemical insights, constraints, and failures to the persistent scratchpad.

    The executor merges new entries on top of the existing scratchpad state
    via the ``merge_scratchpad`` logic -- existing rules are never deleted.
    """

    name = "tool_update_scratchpad"
    args_schema = UpdateScratchpadInput
    tier = "L1"
    max_result_size_chars = 2_000

    async def validate_input(
        self, args: UpdateScratchpadInput, context: dict
    ) -> ValidationResult:
        if not args.established_rules and not args.failed_attempts and not args.research_goal.strip():
            return ValidationResult(result=False, message="所有参数均为空，无需写入黑板。")
        return ValidationResult(result=True)

    def call(self, args: UpdateScratchpadInput) -> str:
        """Update the persistent research scratchpad with new rules, findings, or a goal."""
        return json.dumps(
            {
                "__chem_protocol__": "ScratchpadUpdate",
                "established_rules": [str(r).strip() for r in args.established_rules if str(r).strip()],
                "failed_attempts": [str(f).strip() for f in args.failed_attempts if str(f).strip()],
                "research_goal": args.research_goal.strip(),
            },
            ensure_ascii=False,
        )


tool_update_scratchpad = ToolUpdateScratchpad().as_langchain_tool()


# ── 2. tool_create_molecule_node ──────────────────────────────────────────────


class CreateMoleculeNodeInput(BaseModel):
    smiles: str = Field(
        description="分子的 canonical SMILES（建议先用 tool_validate_smiles 获取规范化字符串）"
    )
    parent_id: str = Field(
        default="",
        description="母本分子的 artifact_id（例如 'mol_a49f7510'）；如果是首个分子则留空",
    )
    creation_operation: str = Field(
        default="",
        description="生成操作的描述（例如 'scaffold_hop_to_pyrrolopyrimidine'）；用于渲染演化树",
    )
    status: str = Field(
        default="staged",
        description=(
            "初始状态：staged | exploring | lead | rejected。"
            "注意：status='lead' 专属于经过 tool_screen_molecules 筛选后留下的分子。"
        ),
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="可选：化合物别名或编号（例如 ['Hop-1', 'CAS 12345-67-8']）",
    )


class ToolCreateMoleculeNode(ChemStateTool[CreateMoleculeNodeInput, str]):
    """Register a new molecule or annotate an existing one with explicit lineage.

    The executor upserts the node (preserving any existing diagnostics) and
    adds its artifact_id to ``viewport.focused_artifact_ids``.
    """

    name = "tool_create_molecule_node"
    args_schema = CreateMoleculeNodeInput
    tier = "L1"
    max_result_size_chars = 1_000

    async def validate_input(
        self, args: CreateMoleculeNodeInput, context: dict
    ) -> ValidationResult:
        if not args.smiles.strip():
            return ValidationResult(result=False, message="smiles 不能为空。")
        return ValidationResult(result=True)

    def call(self, args: CreateMoleculeNodeInput) -> str:
        """Register a new molecule node in the IDE molecule tree for tracking and visualisation."""
        smiles = args.smiles.strip()
        artifact_id = _artifact_id_from_smiles(smiles)
        return json.dumps(
            {
                "__chem_protocol__": "NodeCreate",
                "artifact_id": artifact_id,
                "smiles": smiles,
                "parent_id": args.parent_id.strip() or None,
                "creation_operation": args.creation_operation.strip() or None,
                "status": args.status.strip() or "staged",
                "aliases": [str(a).strip() for a in args.aliases if str(a).strip()],
            },
            ensure_ascii=False,
        )


tool_create_molecule_node = ToolCreateMoleculeNode().as_langchain_tool()


# ── 3. tool_update_viewport ───────────────────────────────────────────────────


class UpdateViewportInput(BaseModel):
    focused_artifact_ids: list[str] = Field(
        description="要在前端分屏对比的 artifact_id 列表（例如 ['mol_a49f7510', 'mol_c6afbf3c']）"
    )
    reference_artifact_id: str = Field(
        default="",
        description="（可选）对比时的参考母本 artifact_id；前端通常高亮显示",
    )


class ToolUpdateViewport(ChemStateTool[UpdateViewportInput, str]):
    """Explicitly switch the IDE molecular viewport to a set of molecules.

    The viewport state is replaced (not appended) by this call.
    """

    name = "tool_update_viewport"
    args_schema = UpdateViewportInput
    tier = "L1"
    max_result_size_chars = 1_000

    async def validate_input(
        self, args: UpdateViewportInput, context: dict
    ) -> ValidationResult:
        ids = [str(i).strip() for i in args.focused_artifact_ids if str(i).strip()]
        if not ids:
            return ValidationResult(result=False, message="focused_artifact_ids 不能为空列表。")
        return ValidationResult(result=True)

    def call(self, args: UpdateViewportInput) -> str:
        """Set which molecule artifact IDs are shown in the IDE 2D/3D viewport."""
        ids = list(dict.fromkeys(str(i).strip() for i in args.focused_artifact_ids if str(i).strip()))
        return json.dumps(
            {
                "__chem_protocol__": "ViewportUpdate",
                "focused_artifact_ids": ids,
                "reference_artifact_id": args.reference_artifact_id.strip() or None,
            },
            ensure_ascii=False,
        )


tool_update_viewport = ToolUpdateViewport().as_langchain_tool()


# ── 4. tool_patch_diagnostics ─────────────────────────────────────────────────


class PatchDiagnosticsInput(BaseModel):
    updates: list[dict] = Field(
        description=(
            '每项格式：{"artifact_id": "mol_*", "diagnostics": {"tpsa": 78.3, "logp": 4.64, ...}}. '
            "diagnostics 字段与现有数据合并，不清空其他字段。"
        )
    )


class ToolPatchDiagnostics(ChemStateTool[PatchDiagnosticsInput, str]):
    """Explicitly write computed property values into molecule_tree diagnostics.

    Use this for any property calculation that does NOT go through a native
    chemistry tool (tool_compute_descriptors etc.).
    """

    name = "tool_patch_diagnostics"
    args_schema = PatchDiagnosticsInput
    tier = "L1"
    max_result_size_chars = 1_000

    async def validate_input(
        self, args: PatchDiagnosticsInput, context: dict
    ) -> ValidationResult:
        cleaned = [
            upd for upd in (args.updates or [])
            if str(upd.get("artifact_id") or "").strip() and upd.get("diagnostics")
        ]
        if not cleaned:
            return ValidationResult(
                result=False,
                message="updates 为空或每项均缺少 artifact_id / diagnostics 字段。",
            )
        return ValidationResult(result=True)

    def call(self, args: PatchDiagnosticsInput) -> str:
        """Write computed properties back to molecule tree diagnostics for screening."""
        cleaned = [
            {"artifact_id": str(upd.get("artifact_id", "")).strip(),
             "diagnostics": dict(upd.get("diagnostics") or {})}
            for upd in (args.updates or [])
            if str(upd.get("artifact_id") or "").strip() and upd.get("diagnostics")
        ]
        return json.dumps(
            {"__chem_protocol__": "BatchNodeUpdate", "updates": cleaned},
            ensure_ascii=False,
        )


tool_patch_diagnostics = ToolPatchDiagnostics().as_langchain_tool()


# ── Catalog ───────────────────────────────────────────────────────────────────

ALL_STATE_TOOLS = [
    tool_update_scratchpad,
    tool_create_molecule_node,
    tool_update_viewport,
    tool_patch_diagnostics,
]

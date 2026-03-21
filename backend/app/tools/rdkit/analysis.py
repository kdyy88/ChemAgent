"""
RDKit molecular analysis agent tool.

Tool registered
---------------
analyze_molecule_from_smiles   SMILES → Lipinski Rule-of-5 + TPSA + 2D image (JSON artifact)

Delegates to ``app.chem.rdkit_ops.compute_lipinski`` — same computation as
the Phase 1 REST endpoint (``POST /api/rdkit/analyze``), ensuring zero drift
between the deterministic API and the agent-callable tool.
"""

from __future__ import annotations

from app.chem.rdkit_ops import compute_lipinski
from app.core.tooling import ToolArtifact, ToolExecutionResult, tool_registry


@tool_registry.register(
    name="analyze_molecule_from_smiles",
    description=(
        "接收标准 SMILES 字符串，验证化学合法性，计算 Lipinski 五规则参数"
        "（分子量 MW、脂水分配系数 LogP、氢键供体 HBD、氢键受体 HBA）以及"
        "极性表面积 TPSA（参考值，不计入评分），并生成 2D 分子结构图。"
        "所有结果以单一 JSON 产物返回，结构图以 Base64 形式嵌入其中。"
    ),
    display_name="Analyzing Molecule…",
    category="analysis",
    reflection_hint=(
        "若 RDKit 报告 invalid_smiles，请重新检查输入的 SMILES 是否含非法字符、"
        "芳香性标记错误或括号不匹配，修正后重试。"
    ),
    output_kinds=("json",),
    tags=("rdkit", "lipinski", "smiles", "analysis"),
)
def analyze_molecule_from_smiles(smiles: str, name: str = "") -> ToolExecutionResult:
    """
    验证 SMILES、计算 Lipinski 五规则参数并生成 2D 结构图。

    委托给 ``compute_lipinski()`` 执行，确保与 Phase 1 REST 端点使用完全相同的
    计算逻辑，不产生任何重复实现。

    返回单一 JSON 产物，结构图（bare base64）内嵌于 data.structure_image 字段。
    前端 LipinskiCard 组件在 JSX 层面拼接 data:image/png;base64, 前缀。
    """
    result = compute_lipinski(smiles, name)

    if not result.get("is_valid"):
        return ToolExecutionResult(
            status="error",
            summary=result.get("error", "SMILES 解析失败。"),
            data={"smiles": smiles},
            error_code="invalid_smiles",
            retry_hint="请检查 SMILES 的环闭合、芳香性、括号匹配和原子价态，修正后重试。",
        )

    props = result["properties"]
    mw    = props["molecular_weight"]["value"]
    logp  = props["log_p"]["value"]
    verdict = "通过" if result["lipinski_pass"] else f"存在 {result['violations']} 条违规，未通过"

    return ToolExecutionResult(
        status="success",
        summary=(
            f"分子分析完成。分子量 {mw} Da，LogP {logp}，{verdict} Lipinski 五规则。"
        ),
        data={},
        artifacts=[
            ToolArtifact(
                kind="json",
                mime_type="application/json",
                encoding="json",
                data=result,
                title=name.strip() if name.strip() else smiles,
                description=f"Lipinski Rule-of-5 analysis for {name or smiles}",
            )
        ],
    )

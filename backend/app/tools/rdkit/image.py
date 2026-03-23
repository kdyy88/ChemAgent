"""
RDKit 2D image agent tools.

Tools registered
----------------
draw_molecules_by_name        Batch: compound name → PubChem SMILES → RDKit 2D PNG
generate_2d_image_from_smiles Single: SMILES → RDKit 2D PNG

Computation is delegated to ``app.chem.rdkit_ops`` (the single source of truth
for all RDKit logic).  This file only handles tool registration and the
PubChem HTTP lookup required by the batch tool.
"""

from __future__ import annotations

from urllib.parse import quote as _url_quote

import httpx
from rdkit import Chem

from app.chem.rdkit_ops import mol_to_png_b64
from app.core.tooling import ToolArtifact, ToolExecutionResult, tool_registry


# ── Tool 1: Batch name → image ────────────────────────────────────────────────


@tool_registry.register(
    name="draw_molecules_by_name",
    description=(
        "批量根据化合物名称绘制 2D 分子结构图。"
        "接受逗号分隔的化合物名称列表（中英文均可），例如 \"Aspirin, Caffeine, Ibuprofen\"。"
        "工具内部自动查询 PubChem 获取 SMILES，再用 RDKit 渲染每一张结构图，"
        "一次调用即可返回全部结构图像。无需分别调用 get_smiles 和 generate_image。"
    ),
    display_name="Generating Molecule Images…",
    category="visualization",
    reflection_hint=(
        "若某化合物检索失败，请用英文学名、IUPAC 名或 INN 名重新列出全部待绘化合物再次调用。"
    ),
    output_kinds=("image", "json"),
    tags=("rdkit", "pubchem", "batch", "smiles", "image"),
)
def draw_molecules_by_name(chemical_names: str) -> ToolExecutionResult:
    """
    批量根据逗号分隔的化合物名称绘制 2D 分子结构图。
    chemical_names: 逗号分隔的化合物名称，例如 "Aspirin, Caffeine, Ibuprofen"
    """
    names = [n.strip() for n in chemical_names.split(",") if n.strip()]
    if not names:
        return ToolExecutionResult(
            status="error",
            summary="未提供任何化合物名称，请传入逗号分隔的名称列表。",
            data={},
            error_code="no_input",
        )

    all_artifacts: list[ToolArtifact] = []
    successes:     list[str]          = []
    failed_items:  list[dict]         = []

    for name in names:
        # ── PubChem SMILES lookup ─────────────────────────────────────────
        url = (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
            f"{_url_quote(name)}/property/CanonicalSMILES/TXT"
        )
        try:
            resp = httpx.get(url, timeout=12.0)
        except httpx.HTTPError as exc:
            failed_items.append({"name": name, "reason": f"网络错误 – {exc}"})
            continue

        if resp.status_code == 404:
            failed_items.append({
                "name": name,
                "reason": "PubChem 数据库未收录此名称，请改用英文 INN/USAN 学名或 IUPAC 名",
            })
            continue
        if resp.status_code != 200:
            failed_items.append({
                "name": name,
                "reason": f"PubChem 返回异常状态码 {resp.status_code}",
            })
            continue

        smiles = resp.text.strip()

        # ── RDKit render ──────────────────────────────────────────────────
        try:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                failed_items.append({"name": name, "reason": "RDKit 无法解析 SMILES，结构可能有误"})
                continue
            img_b64 = mol_to_png_b64(mol, size=(400, 400))
        except Exception as exc:  # noqa: BLE001
            failed_items.append({"name": name, "reason": f"RDKit 渲染异常 – {exc}"})
            continue

        all_artifacts.append(
            ToolArtifact(
                kind="image",
                mime_type="image/png",
                data=img_b64,
                encoding="base64",
                title=name,
                description=f"2D structure of {name}",
            )
        )
        successes.append(name)

    # ── Build result ──────────────────────────────────────────────────────────
    if not all_artifacts:
        per_item = "；".join(f"[{i['name']}] {i['reason']}" for i in failed_items)
        return ToolExecutionResult(
            status="error",
            summary=f"全部 {len(names)} 个化合物均处理失败。逐项原因：{per_item}",
            data={"requested": names, "succeeded": [], "failed": failed_items},
            error_code="all_failed",
            retry_hint="请对每个失败名称单独反思并改用英文 INN/USAN 名或 IUPAC 系统名后重新调用。",
        )

    summary_parts = [f"已成功生成 {len(successes)}/{len(names)} 个分子结构图：{', '.join(successes)}。"]
    if failed_items:
        per_item = "；".join(f"[{i['name']}] {i['reason']}" for i in failed_items)
        summary_parts.append(f"以下名称处理失败，请逐一核查并重试：{per_item}")

    return ToolExecutionResult(
        status="success",
        summary=" ".join(summary_parts),
        data={"requested": names, "succeeded": successes, "failed": failed_items},
        artifacts=all_artifacts,
    )


# ── Tool 2: Single SMILES → image ─────────────────────────────────────────────


@tool_registry.register(
    name="generate_2d_image_from_smiles",
    description=(
        "将标准 SMILES 转换为高质量 2D 分子结构图，并以 PNG Base64 产物返回。"
        "可选传入化合物名称 name 用于标注图片标题。"
    ),
    display_name="Generating 2D Structure…",
    category="visualization",
    reflection_hint=(
        "若 RDKit 解析失败，请重新检查环闭合、芳香性、原子价态与括号层级，修正 SMILES 后重试。"
    ),
    output_kinds=("image",),
    tags=("rdkit", "image", "smiles"),
)
def generate_2d_image_from_smiles(smiles: str, name: str = "") -> ToolExecutionResult:
    """
    接收 SMILES 字符串，使用 RDKit 解析并生成 2D 图像。
    name 可选，传入化合物名作为图片标题（如 "Aspirin"）。
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return ToolExecutionResult(
                status="error",
                summary=f"RDKit 无法解析 SMILES: {smiles}",
                data={"smiles": smiles},
                error_code="invalid_smiles",
                retry_hint="请检查环闭合、芳香性、括号匹配和原子价态，修正后再重新绘图。",
            )

        img_b64 = mol_to_png_b64(mol, size=(400, 400))
        label   = name.strip() if name and name.strip() else smiles

        return ToolExecutionResult(
            status="success",
            summary="已成功生成 2D 分子结构图。",
            data={"smiles": smiles, "image_format": "png"},
            artifacts=[
                ToolArtifact(
                    kind="image",
                    mime_type="image/png",
                    data=img_b64,
                    encoding="base64",
                    title=label,
                    description=f"RDKit generated structure for {name or smiles}",
                )
            ],
        )

    except Exception as exc:  # noqa: BLE001
        return ToolExecutionResult(
            status="error",
            summary="RDKit 工具发生未知异常。",
            data={"smiles": smiles, "detail": str(exc)},
            error_code="rdkit_exception",
            retry_hint="请确认输入是标准 SMILES；若仍失败，可先重新检索更权威的结构来源。",
        )

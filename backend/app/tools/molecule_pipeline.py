"""
Batch molecule pipeline tool.

Single-call tool: PubChem SMILES lookup → RDKit 2D render for N molecules.
Eliminates the need for the LLM to loop; all artifacts are returned at once.
"""
from __future__ import annotations

import base64
from io import BytesIO

import requests
from rdkit import Chem
from rdkit.Chem import Draw

from app.core.tooling import ToolArtifact, ToolExecutionResult, tool_registry


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
    每个名称依次：
      1. 调用 PubChem REST API 获取 Canonical SMILES
      2. 使用 RDKit 渲染 400×400 PNG 结构图
    最终在一个 ToolExecutionResult 中返回全部成功图像的 artifacts。
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
    successes: list[str] = []
    # Each entry: {"name": str, "reason": str} — structured so LLM knows exactly which name failed
    failed_items: list[dict[str, str]] = []

    for name in names:
        # ── Step 1: PubChem SMILES lookup ────────────────────────────────
        url = (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
            f"{requests.utils.quote(name)}/property/CanonicalSMILES/TXT"
        )
        try:
            resp = requests.get(url, timeout=12)
        except requests.exceptions.RequestException as exc:
            failed_items.append({"name": name, "reason": f"网络错误 – {exc}"})
            continue

        if resp.status_code == 404:
            failed_items.append({"name": name, "reason": "PubChem 数据库未收录此名称，请改用英文 INN/USAN 学名或 IUPAC 名"})
            continue
        if resp.status_code != 200:
            failed_items.append({"name": name, "reason": f"PubChem 返回异常状态码 {resp.status_code}"})
            continue

        smiles = resp.text.strip()

        # ── Step 2: RDKit render ─────────────────────────────────────────
        try:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                failed_items.append({"name": name, "reason": f"RDKit 无法解析 SMILES，结构可能有误"})
                continue

            img = Draw.MolToImage(mol, size=(400, 400))
            buf = BytesIO()
            img.save(buf, format="PNG")
            img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
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

    # ── Build result ─────────────────────────────────────────────────────
    has_failures = len(failed_items) > 0

    if not all_artifacts:
        # Every name failed — list each one explicitly
        per_item_summary = "；".join(
            f"[{item['name']}] {item['reason']}" for item in failed_items
        )
        return ToolExecutionResult(
            status="error",
            summary=f"全部 {len(names)} 个化合物均处理失败。逐项原因：{per_item_summary}",
            data={
                "requested": names,
                "succeeded": [],
                "failed": failed_items,
            },
            error_code="all_failed",
            retry_hint="请对每个失败名称单独反思并改用英文 INN/USAN 名或 IUPAC 系统名后重新调用。",
        )

    # Partial or full success
    summary_parts = [f"已成功生成 {len(successes)}/{len(names)} 个分子结构图：{', '.join(successes)}。"]
    if has_failures:
        per_item_errors = "；".join(
            f"[{item['name']}] {item['reason']}" for item in failed_items
        )
        summary_parts.append(f"以下名称处理失败，请逐一核查并重试：{per_item_errors}")

    return ToolExecutionResult(
        status="success",  # partial success: artifacts present, failed items listed in data.failed + summary
        summary=" ".join(summary_parts),
        data={
            "requested": names,
            "succeeded": successes,
            "failed": failed_items,  # list of {name, reason}
        },
        artifacts=all_artifacts,
    )

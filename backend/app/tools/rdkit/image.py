"""
RDKit molecular visualization agent tool.

Tool registered
---------------
draw_molecules_by_name   compound names → PubChem SMILES → RDKit 2D structure images

Accepts a comma-separated list of compound names in English, resolves each to
a canonical SMILES via the PubChem REST API, then renders a 2D structure image
using RDKit.  Each image is returned as a base64-encoded PNG artifact.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
import json

from rdkit import Chem

from app.chem.rdkit_ops import mol_to_png_b64
from app.core.tooling import ToolArtifact, ToolExecutionResult, tool_registry

_PUBCHEM_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name"
    "/{name}/property/IsomericSMILES/JSON"
)


def _fetch_smiles(name: str) -> str | None:
    """Return canonical SMILES from PubChem for a compound name, or None."""
    url = _PUBCHEM_URL.format(name=urllib.parse.quote(name.strip()))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "chem-agent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode())
        props = payload["PropertyTable"]["Properties"]
        entry = props[0]
        # PubChem may return either key depending on stereo data availability
        return entry.get("IsomericSMILES") or entry.get("SMILES")
    except Exception:
        return None


@tool_registry.register(
    name="draw_molecules_by_name",
    description=(
        "接收一个或多个化合物的英文名称（以英文逗号分隔），通过 PubChem 查询对应的 SMILES，"
        "然后使用 RDKit 生成每个化合物的 2D 分子结构图，以 PNG 图像产物返回。"
        "如果某个化合物无法找到，结果中的 data.failed 列表会记录失败原因。"
        "示例输入：\"aspirin, caffeine, ibuprofen\""
    ),
    display_name="Drawing Structures…",
    category="visualization",
    reflection_hint=(
        "若某化合物解析失败，请检查名称是否为标准英文名（INN、IUPAC 或常用名）。"
        "混合物、商品名或过于模糊的名称可能导致 PubChem 查询失败，可尝试使用 SMILES 直接绘制。"
    ),
    output_kinds=("image",),
    tags=("rdkit", "pubchem", "structure", "visualization"),
)
def draw_molecules_by_name(chemical_names: str) -> ToolExecutionResult:
    """
    将化合物英文名称解析为 SMILES，并生成 2D 结构图。

    参数
    ----
    chemical_names : str
        英文化合物名称，多个名称用英文逗号分隔。
    """
    names = [n.strip() for n in chemical_names.split(",") if n.strip()]
    if not names:
        return ToolExecutionResult(
            status="error",
            summary="未提供任何化合物名称。",
            error_code="EMPTY_INPUT",
        )

    artifacts: list[ToolArtifact] = []
    failed: list[dict] = []

    for name in names:
        smiles = _fetch_smiles(name)
        if smiles is None:
            failed.append({"name": name, "reason": "PubChem 未找到该化合物"})
            continue

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            failed.append({"name": name, "reason": f"RDKit 无法解析 SMILES：{smiles}"})
            continue

        try:
            png_b64 = mol_to_png_b64(mol, size=(400, 400))
        except Exception as exc:
            failed.append({"name": name, "reason": f"图像生成失败：{exc}"})
            continue

        artifacts.append(
            ToolArtifact(
                kind="image",
                mime_type="image/png",
                encoding="base64",
                data=png_b64,
                title=name,
                description=f"{name} 的 2D 结构图（SMILES: {smiles}）",
            )
        )

    success_count = len(artifacts)
    fail_count = len(failed)

    if success_count == 0:
        summary = f"所有 {fail_count} 个化合物均解析失败。"
        status = "error"
    elif fail_count == 0:
        summary = f"成功绘制 {success_count} 个结构图。"
        status = "success"
    else:
        summary = f"成功绘制 {success_count} 个结构图，{fail_count} 个解析失败。"
        status = "success"

    return ToolExecutionResult(
        status=status,
        summary=summary,
        data={"failed": failed},
        artifacts=artifacts,
    )

from __future__ import annotations

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.runnables import RunnableConfig

from app.agents.utils import ToolPostprocessor, ToolResult, refresh_result, strip_binary_fields
from app.chem.babel_ops import build_3d_conformer, convert_format, prepare_pdbqt
from app.chem.rdkit_ops import compute_descriptors, substructure_match


async def _dispatch_artifact(artifacts: list[dict], artifact: dict, config: RunnableConfig) -> None:
    artifacts.append(artifact)
    await adispatch_custom_event("artifact", artifact, config=config)


async def postprocess_render_smiles(
    parsed: ToolResult,
    _args: dict[str, object],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    if parsed.get("is_valid") and parsed.get("image"):
        compound_name = parsed.get("compound_name") or str(_args.get("compound_name", ""))
        highlight_atoms = parsed.get("highlight_atoms", [])
        if compound_name and highlight_atoms:
            title = f"{compound_name} · 高亮结构图"
        elif compound_name:
            title = f"{compound_name} · 2D 结构图"
        else:
            title = "2D 分子结构图"
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "molecule_image",
                "title": title,
                "smiles": parsed.get("smiles"),
                "image": parsed.get("image"),
                "highlight_atoms": highlight_atoms,
            },
            config,
        )
        return {
            "status": "success",
            "message": "2D结构图已发送给用户",
            "smiles": parsed.get("smiles"),
            "highlight_atoms": highlight_atoms,
        }
    return parsed


async def postprocess_descriptors(
    parsed: ToolResult,
    args: dict[str, object],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    detailed = refresh_result(
        parsed,
        required_key="structure_image",
        loader=lambda: compute_descriptors(str(args.get("smiles", "")), str(args.get("name", ""))),
    )
    if detailed.get("structure_image"):
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "descriptor_structure_image",
                "title": detailed.get("name") or "分子结构图",
                "smiles": detailed.get("smiles"),
                "image": detailed.get("structure_image"),
            },
            config,
        )
        summary = strip_binary_fields(detailed)
        summary["message"] = "描述符结果已生成，结构图已发送给用户"
        return summary
    return detailed


async def postprocess_substructure_match(
    parsed: ToolResult,
    args: dict[str, object],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    detailed = refresh_result(
        parsed,
        required_key="highlighted_image",
        loader=lambda: substructure_match(str(args.get("smiles", "")), str(args.get("smarts_pattern", ""))),
    )
    if detailed.get("highlighted_image"):
        # Build a human-readable title from optional name parameters
        compound = detailed.get("compound_name") or str(args.get("compound_name", ""))
        substruct = detailed.get("substructure_name") or str(args.get("substructure_name", ""))
        if compound and substruct:
            title = f"{compound} · {substruct} 子结构高亮"
        elif compound:
            title = f"{compound} · 子结构高亮图"
        elif substruct:
            title = f"{substruct} 子结构高亮图"
        else:
            title = "子结构高亮图"
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "highlighted_substructure",
                "title": title,
                "smiles": detailed.get("smiles"),
                "image": detailed.get("highlighted_image"),
                "match_atoms": detailed.get("match_atoms", []),
            },
            config,
        )
        summary = strip_binary_fields(detailed)
        summary["message"] = "子结构匹配完成，高亮图已发送给用户"
        return summary
    return detailed


async def postprocess_build_3d_conformer(
    parsed: ToolResult,
    args: dict[str, object],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    detailed = refresh_result(
        parsed,
        required_key="sdf_content",
        loader=lambda: build_3d_conformer(
            str(args.get("smiles", "")),
            name=str(args.get("name", "")),
            forcefield=str(args.get("forcefield", "mmff94")),
            steps=int(args.get("steps", 500)),
        ),
    )
    if detailed.get("sdf_content"):
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "conformer_sdf",
                "title": detailed.get("name") or "3D 构象 SDF",
                "smiles": detailed.get("smiles"),
                "sdf_content": detailed.get("sdf_content"),
                "energy": detailed.get("energy_kcal_mol"),
            },
            config,
        )
        summary = strip_binary_fields(detailed)
        summary["message"] = "3D构象已生成，SDF 文件已发送给用户"
        return summary
    return detailed


async def postprocess_prepare_pdbqt(
    parsed: ToolResult,
    args: dict[str, object],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    detailed = refresh_result(
        parsed,
        required_key="pdbqt_content",
        loader=lambda: prepare_pdbqt(
            str(args.get("smiles", "")),
            name=str(args.get("name", "")),
            ph=float(args.get("ph", 7.4)),
        ),
    )
    if detailed.get("pdbqt_content"):
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "pdbqt_file",
                "title": detailed.get("name") or "PDBQT 配体文件",
                "smiles": detailed.get("smiles"),
                "pdbqt_content": detailed.get("pdbqt_content"),
                "rotatable_bonds": detailed.get("rotatable_bonds"),
            },
            config,
        )
        summary = strip_binary_fields(detailed)
        summary["message"] = "PDBQT 文件已生成并发送给用户"
        return summary
    return detailed


async def postprocess_convert_format(
    parsed: ToolResult,
    args: dict[str, object],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    detailed = parsed
    if len(str(detailed.get("output", ""))) >= 500:
        detailed = convert_format(
            str(args.get("molecule_str", "")),
            str(args.get("input_fmt", "")),
            str(args.get("output_fmt", "")),
        )

    full_output = str(detailed.get("output", ""))
    if full_output and len(full_output) >= 500:
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "format_conversion",
                "title": f"格式转换 → {detailed.get('output_format', '').upper()}",
                "input_format": detailed.get("input_format"),
                "output_format": detailed.get("output_format"),
                "output": full_output,
            },
            config,
        )
        summary = dict(detailed)
        summary["output"] = f"已生成 {detailed.get('output_format', '').upper()} 内容，完整结果已发送给用户"
        return summary
    return detailed


TOOL_POSTPROCESSORS: dict[str, ToolPostprocessor] = {
    "tool_render_smiles": postprocess_render_smiles,
    "tool_compute_descriptors": postprocess_descriptors,
    "tool_substructure_match": postprocess_substructure_match,
    "tool_build_3d_conformer": postprocess_build_3d_conformer,
    "tool_prepare_pdbqt": postprocess_prepare_pdbqt,
    "tool_convert_format": postprocess_convert_format,
}
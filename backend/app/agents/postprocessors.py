from __future__ import annotations

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.runnables import RunnableConfig

from app.agents.utils import ToolPostprocessor, ToolResult, refresh_result, strip_binary_fields
from app.chem.babel_ops import build_3d_conformer, convert_format, prepare_pdbqt
from app.chem.rdkit_ops import compute_descriptors, substructure_match


async def _resolve_smiles_for_postprocessor(
    parsed: ToolResult,
    args: dict[str, object],
) -> str:
    smiles = str(parsed.get("smiles") or args.get("smiles") or "").strip()
    if smiles:
        return smiles

    artifact_id = str(parsed.get("artifact_id") or args.get("artifact_id") or "").strip()
    if not artifact_id:
        return ""

    from app.core.artifact_store import get_engine_artifact  # noqa: PLC0415

    record = await get_engine_artifact(artifact_id)
    if isinstance(record, dict):
        return str(record.get("canonical_smiles") or "").strip()
    return ""

# Fields that are dispatched via SSE artifact event but must NOT be stored in
# ChemState.artifacts (operator.add accumulator).  Keeping raw binary data in
# the LangGraph state causes unbounded checkpoint growth and pollutes debug logs.
_STATE_STRIP_FIELDS: frozenset[str] = frozenset({
    "image", "structure_image", "highlighted_image",
    "molecule_image", "scaffold_image",
    "sdf_content", "pdbqt_content",
})


def _strip_for_state(artifact: dict) -> dict:
    """Return a copy of artifact without large binary fields for state storage."""
    return {k: v for k, v in artifact.items() if k not in _STATE_STRIP_FIELDS}


async def _dispatch_artifact(artifacts: list[dict], artifact: dict, config: RunnableConfig) -> None:
    # State list gets a lean copy (no binary blobs); SSE gets the full payload.
    artifacts.append(_strip_for_state(artifact))
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
    smiles = await _resolve_smiles_for_postprocessor(parsed, args)
    detailed = parsed if parsed.get("structure_image") else (
        compute_descriptors(smiles, str(parsed.get("name") or args.get("name", "")))
        if smiles else parsed
    )
    if detailed.get("structure_image"):
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "descriptor_structure_image",
                "title": detailed.get("name") or "分子结构图",
                "smiles": detailed.get("smiles"),
                "artifact_id": parsed.get("artifact_id"),
                "image": detailed.get("structure_image"),
            },
            config,
        )
        summary = strip_binary_fields(detailed)
        if parsed.get("artifact_id"):
            summary["artifact_id"] = parsed.get("artifact_id")
        summary["message"] = "描述符结果已生成，结构图已发送给用户"
        return summary
    return detailed


async def postprocess_evaluate_molecule(
    parsed: ToolResult,
    args: dict[str, object],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    smiles = await _resolve_smiles_for_postprocessor(parsed, args)
    detailed = compute_descriptors(smiles, str(parsed.get("name") or args.get("name", ""))) if smiles else parsed

    if detailed.get("structure_image") and parsed.get("artifact_id"):
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "descriptor_structure_image",
                "title": parsed.get("name") or detailed.get("name") or "分子结构图",
                "smiles": parsed.get("smiles") or detailed.get("smiles"),
                "artifact_id": parsed.get("artifact_id"),
                "parent_artifact_id": parsed.get("parent_artifact_id"),
                "image": detailed.get("structure_image"),
            },
            config,
        )

    summary = dict(parsed)
    if detailed.get("structure_image"):
        summary["message"] = "分子评估已完成，描述符与结构图已发送给用户"
    return summary


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


async def postprocess_murcko_scaffold(
    parsed: ToolResult,
    _args: dict[str, object],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    if parsed.get("molecule_image"):
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "molecule_image",
                "title": "原分子结构图",
                "smiles": parsed.get("smiles"),
                "image": parsed.get("molecule_image"),
            },
            config,
        )

    if parsed.get("scaffold_image"):
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "scaffold_image",
                "title": "Murcko Scaffold 结构图",
                "smiles": parsed.get("scaffold_smiles"),
                "source_smiles": parsed.get("smiles"),
                "image": parsed.get("scaffold_image"),
            },
            config,
        )

    summary = strip_binary_fields(parsed)
    if parsed.get("is_valid"):
        summary["message"] = "Murcko scaffold 已提取，结构图已发送给用户"
    return summary


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
            steps=int(str(args.get("steps", 500))),
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
            ph=float(str(args.get("ph", 7.4))),
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


async def postprocess_web_search(
    parsed: ToolResult,
    args: dict[str, object],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    results: list[dict] = parsed.get("results", [])  # type: ignore[assignment]
    if results and parsed.get("status") == "success":
        sources = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("snippet", "")}
            for r in results[:8]
            if r.get("url")
        ]
        if sources:
            await _dispatch_artifact(
                artifacts,
                {
                    "kind": "web_search_sources",
                    "query": parsed.get("query") or str(args.get("query", "")),
                    "sources": sources,
                },
                config,
            )
    # Return a compact summary so the LLM doesn't re-echo all raw text
    return {
        "status": parsed.get("status"),
        "query": parsed.get("query"),
        "result_count": len(results),
        "message": f"已找到 {len(results)} 条结果，来源列表已展示给用户",
        # Keep first result snippet for the LLM to reason with
        "top_result": results[0] if results else None,
    }


TOOL_POSTPROCESSORS: dict[str, ToolPostprocessor] = {
    "tool_render_smiles": postprocess_render_smiles,
    "tool_evaluate_molecule": postprocess_evaluate_molecule,
    "tool_compute_descriptors": postprocess_descriptors,
    "tool_substructure_match": postprocess_substructure_match,
    "tool_murcko_scaffold": postprocess_murcko_scaffold,
    "tool_build_3d_conformer": postprocess_build_3d_conformer,
    "tool_prepare_pdbqt": postprocess_prepare_pdbqt,
    "tool_convert_format": postprocess_convert_format,
    "tool_web_search": postprocess_web_search,
}
"""Unified Chem ReAct graph for ChemAgent.

This graph intentionally avoids a supervisor / specialist-router pattern.
Instead, a single `chem_agent` node reasons over the full conversation and
selects tools in a continuous ReAct loop, while `tools_executor` performs tool
execution, artifact dispatch, and explicit `active_smiles` state updates.
"""

from __future__ import annotations

import json
import operator
from typing import Annotated, Any

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.agents.config import build_llm_config
from app.agents.lg_tools import ALL_CHEM_TOOLS
from app.chem.babel_ops import build_3d_conformer, convert_format, prepare_pdbqt
from app.chem.rdkit_ops import compute_descriptors, substructure_match

_STRIP_LLM_FIELDS = frozenset({
    "image", "structure_image", "highlighted_image",
    "sdf_content", "pdbqt_content", "zip_bytes", "atoms",
})


CHEM_SYSTEM_PROMPT = """你是顶级化学智能体 ChemAgent。你可以同时调用 RDKit 与 Open Babel 工具。

【核心工作流法则】
1. 采用 ReAct 工作流：先思考，再调用工具，再读取结果，然后继续下一步。
2. 你可以连续调用多个工具；上一个工具的输出就是下一个工具的输入依据。
3. 当前全局最新 SMILES 是：{active_smiles}
4. 如果调用了 `tool_strip_salts`、`tool_murcko_scaffold`、`tool_validate_smiles` 或 `tool_pubchem_lookup` 并拿到了新的 SMILES，下一个工具必须优先使用这个新 SMILES，绝不能回退到用户最初输入的旧 SMILES。
5. 如果不确定下一步该使用哪个 SMILES，请优先使用当前状态中的 `active_smiles`。
6. 如果需要生成 3D 构象、PDBQT、MOL2 等 Open Babel 结果，优先确保使用的是干净、可用的 SMILES。
7. 绝不要编造工具结果；所有结论都必须基于现有消息与工具返回。

【特殊任务指南】
- 如果用户要求计算理化性质、Lipinski、QED、TPSA、相似度、骨架、子结构，使用 RDKit 相关工具。
- 如果用户要求格式转换、3D 构象、PDBQT、部分电荷、Open Babel 交叉验证，使用 Open Babel 相关工具。
- 如果用户要求在图上高亮某个骨架或子结构，先用 `tool_substructure_match` 获取 `match_atoms`，再将它们作为 `highlight_atoms` 传给 `tool_render_smiles`。
- 如果只有化合物名称而没有 SMILES，可先使用 `tool_pubchem_lookup`。
- 如果信息不足且确实无法继续，再使用 `tool_ask_human`。

【输出要求】
- 工具调用完成后，用中文给出清晰、专业、简洁的最终回答。
- 当已经有足够信息时，不要继续调用工具。
"""


class ChemState(TypedDict):
    """Unified graph state for the chem ReAct agent."""
    messages: Annotated[list[BaseMessage], add_messages]
    active_smiles: str | None
    artifacts: Annotated[list[dict], operator.add]


# ── Utility Functions ─────────────────────────────────────────────────────────

def _strip_binary_fields(data: dict) -> dict:
    """Remove binary fields before sending to LLM."""
    return {k: v for k, v in data.items() if k not in _STRIP_LLM_FIELDS}


def _tool_result_to_text(result: dict) -> str:
    """Convert tool result to JSON text for LLM."""
    cleaned = _strip_binary_fields(result)
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


def _parse_tool_output(output: Any) -> dict[str, Any] | None:
    """Parse JSON-like tool outputs into dictionaries when possible."""
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _current_smiles_text(active_smiles: str | None) -> str:
    return active_smiles or "（无）"


def _build_tool_lookup() -> dict[str, Any]:
    return {tool.name: tool for tool in ALL_CHEM_TOOLS}


# ── LLM Factory ───────────────────────────────────────────────────────────────

def _build_llm(structured_schema: type | None = None) -> Any:
    """Build ChatOpenAI with optional structured output."""
    config_dict = build_llm_config()
    config = config_dict["config_list"][0]
    
    llm = ChatOpenAI(**config)
    if structured_schema:
        llm = llm.with_structured_output(structured_schema)
    return llm


# ── Nodes ─────────────────────────────────────────────────────────────────────

async def chem_agent_node(state: ChemState) -> dict:
    """Unified reasoning node that decides whether to call tools or answer."""
    llm = _build_llm()
    llm_with_tools = llm.bind_tools(ALL_CHEM_TOOLS)

    response = await llm_with_tools.ainvoke([
        SystemMessage(content=CHEM_SYSTEM_PROMPT.format(active_smiles=_current_smiles_text(state.get("active_smiles")))),
        *state["messages"],
    ])
    return {"messages": [response]}


async def tools_executor_node(state: ChemState, config: RunnableConfig) -> dict:
    """Execute tool calls, dispatch artifacts, and update explicit state."""
    last_message = state["messages"][-1]
    tool_lookup = _build_tool_lookup()
    new_active_smiles = state.get("active_smiles")
    artifacts: list[dict] = []
    tool_messages: list[ToolMessage] = []

    for tool_call in getattr(last_message, "tool_calls", []):
        tool_name = tool_call["name"]
        tool_call_id = tool_call.get("id", "")
        args = tool_call.get("args", {})
        tool = tool_lookup.get(tool_name)

        if tool is None:
            tool_messages.append(ToolMessage(
                content=json.dumps({"error": f"Tool {tool_name} not found"}, ensure_ascii=False),
                tool_call_id=tool_call_id,
                name=tool_name,
            ))
            continue

        try:
            raw_output = await tool.ainvoke(args, config=config)
            parsed = _parse_tool_output(raw_output)

            if parsed is not None:
                if tool_name == "tool_strip_salts" and parsed.get("is_valid"):
                    new_active_smiles = parsed.get("cleaned_smiles") or new_active_smiles

                elif tool_name == "tool_pubchem_lookup" and parsed.get("found"):
                    new_active_smiles = parsed.get("canonical_smiles") or new_active_smiles

                elif tool_name == "tool_validate_smiles" and parsed.get("is_valid"):
                    new_active_smiles = parsed.get("canonical_smiles") or new_active_smiles

                elif tool_name == "tool_murcko_scaffold" and parsed.get("is_valid"):
                    new_active_smiles = parsed.get("scaffold_smiles") or new_active_smiles

                if tool_name == "tool_render_smiles" and parsed.get("is_valid") and parsed.get("image"):
                    artifact = {
                        "kind": "molecule_image",
                        "title": "2D 分子结构图",
                        "smiles": parsed.get("smiles"),
                        "image": parsed.get("image"),
                        "highlight_atoms": parsed.get("highlight_atoms", []),
                    }
                    artifacts.append(artifact)
                    await adispatch_custom_event("artifact", artifact, config=config)
                    parsed = {
                        "status": "success",
                        "message": "2D结构图已发送给用户",
                        "smiles": parsed.get("smiles"),
                        "highlight_atoms": parsed.get("highlight_atoms", []),
                    }

                elif tool_name == "tool_compute_descriptors":
                    detailed = parsed
                    if not detailed.get("structure_image"):
                        detailed = compute_descriptors(
                            args.get("smiles", ""),
                            args.get("name", ""),
                        )

                    if detailed.get("structure_image"):
                        artifact = {
                            "kind": "descriptor_structure_image",
                            "title": detailed.get("name") or "分子结构图",
                            "smiles": detailed.get("smiles"),
                            "image": detailed.get("structure_image"),
                        }
                        artifacts.append(artifact)
                        await adispatch_custom_event("artifact", artifact, config=config)
                        parsed = _strip_binary_fields(detailed)
                        parsed["message"] = "描述符结果已生成，结构图已发送给用户"

                elif tool_name == "tool_substructure_match":
                    detailed = parsed
                    if not detailed.get("highlighted_image"):
                        detailed = substructure_match(
                            args.get("smiles", ""),
                            args.get("smarts_pattern", ""),
                        )

                    if detailed.get("highlighted_image"):
                        artifact = {
                            "kind": "highlighted_substructure",
                            "title": "子结构高亮图",
                            "smiles": detailed.get("smiles"),
                            "image": detailed.get("highlighted_image"),
                            "match_atoms": detailed.get("match_atoms", []),
                        }
                        artifacts.append(artifact)
                        await adispatch_custom_event("artifact", artifact, config=config)
                        parsed = _strip_binary_fields(detailed)
                        parsed["message"] = "子结构匹配完成，高亮图已发送给用户"

                elif tool_name == "tool_build_3d_conformer":
                    detailed = parsed
                    if not detailed.get("sdf_content"):
                        detailed = build_3d_conformer(
                            args.get("smiles", ""),
                            name=args.get("name", ""),
                            forcefield=args.get("forcefield", "mmff94"),
                            steps=args.get("steps", 500),
                        )

                    if detailed.get("sdf_content"):
                        artifact = {
                            "kind": "conformer_sdf",
                            "title": detailed.get("name") or "3D 构象 SDF",
                            "smiles": detailed.get("smiles"),
                            "sdf_content": detailed.get("sdf_content"),
                            "energy": detailed.get("energy_kcal_mol"),
                        }
                        artifacts.append(artifact)
                        await adispatch_custom_event("artifact", artifact, config=config)
                        parsed = _strip_binary_fields(detailed)
                        parsed["message"] = "3D构象已生成，SDF 文件已发送给用户"

                elif tool_name == "tool_prepare_pdbqt":
                    detailed = parsed
                    if not detailed.get("pdbqt_content"):
                        detailed = prepare_pdbqt(
                            args.get("smiles", ""),
                            name=args.get("name", ""),
                            ph=args.get("ph", 7.4),
                        )

                    if detailed.get("pdbqt_content"):
                        artifact = {
                            "kind": "pdbqt_file",
                            "title": detailed.get("name") or "PDBQT 配体文件",
                            "smiles": detailed.get("smiles"),
                            "pdbqt_content": detailed.get("pdbqt_content"),
                            "rotatable_bonds": detailed.get("rotatable_bonds"),
                        }
                        artifacts.append(artifact)
                        await adispatch_custom_event("artifact", artifact, config=config)
                        parsed = _strip_binary_fields(detailed)
                        parsed["message"] = "PDBQT 文件已生成并发送给用户"

                elif tool_name == "tool_convert_format":
                    detailed = parsed
                    output_preview = str(detailed.get("output", ""))
                    if len(output_preview) >= 500:
                        detailed = convert_format(
                            args.get("molecule_str", ""),
                            args.get("input_fmt", ""),
                            args.get("output_fmt", ""),
                        )

                    full_output = str(detailed.get("output", ""))
                    if full_output and len(full_output) >= 500:
                        artifact = {
                            "kind": "format_conversion",
                            "title": f"格式转换 → {detailed.get('output_format', '').upper()}",
                            "input_format": detailed.get("input_format"),
                            "output_format": detailed.get("output_format"),
                            "output": full_output,
                        }
                        artifacts.append(artifact)
                        await adispatch_custom_event("artifact", artifact, config=config)
                        parsed = dict(detailed)
                        parsed["output"] = f"已生成 {detailed.get('output_format', '').upper()} 内容，完整结果已发送给用户"

                elif tool_name == "tool_ask_human" and parsed.get("type") == "clarification_requested":
                    payload = {
                        "question": parsed.get("question", ""),
                        "options": parsed.get("options", []),
                        "called_tools": [tool_name],
                    }
                    await adispatch_custom_event("clarification_request", payload, config=config)

            content = _tool_result_to_text(parsed) if parsed is not None else str(raw_output)
            tool_messages.append(ToolMessage(
                content=content,
                tool_call_id=tool_call_id,
                name=tool_name,
            ))

        except Exception as exc:
            tool_messages.append(ToolMessage(
                content=json.dumps({"error": str(exc)}, ensure_ascii=False),
                tool_call_id=tool_call_id,
                name=tool_name,
            ))

    return {
        "messages": tool_messages,
        "active_smiles": new_active_smiles,
        "artifacts": artifacts,
    }


# ── Graph Construction ────────────────────────────────────────────────────────

def build_graph() -> Any:
    """Build the unified chem ReAct graph."""
    graph = StateGraph(ChemState)

    graph.add_node("chem_agent", chem_agent_node)
    graph.add_node("tools_executor", tools_executor_node)

    graph.add_edge(START, "chem_agent")

    def route_from_agent(state: ChemState) -> str:
        last_message = state["messages"][-1]
        return "tools_executor" if getattr(last_message, "tool_calls", None) else "__end__"

    graph.add_conditional_edges(
        "chem_agent",
        route_from_agent,
        {
            "tools_executor": "tools_executor",
            "__end__": END,
        }
    )

    graph.add_edge("tools_executor", "chem_agent")

    return graph.compile()


# ── Export ────────────────────────────────────────────────────────────────────

graph: Any = build_graph()
compiled_graph: Any = graph  # Backward compatibility


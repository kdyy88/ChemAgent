"""Unified Chem ReAct graph for ChemAgent.

This graph intentionally avoids a supervisor / specialist-router pattern.
Instead, a single `chem_agent` node reasons over the full conversation and
selects tools in a continuous ReAct loop, while `tools_executor` performs tool
execution, artifact dispatch, and explicit `active_smiles` state updates.
"""

from __future__ import annotations

import json
import operator
from typing import Annotated, Any, Awaitable, Callable, Literal

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
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from app.agents.config import build_llm_config
from app.agents.lg_tools import ALL_CHEM_TOOLS
from app.chem.babel_ops import build_3d_conformer, convert_format, prepare_pdbqt
from app.chem.rdkit_ops import compute_descriptors, substructure_match

_STRIP_LLM_FIELDS = frozenset({
    "image", "structure_image", "highlighted_image",
    "sdf_content", "pdbqt_content", "zip_bytes", "atoms",
})

_ACTIVE_SMILES_UPDATES: dict[str, tuple[str, str]] = {
    "tool_strip_salts": ("is_valid", "cleaned_smiles"),
    "tool_pubchem_lookup": ("found", "canonical_smiles"),
    "tool_validate_smiles": ("is_valid", "canonical_smiles"),
    "tool_murcko_scaffold": ("is_valid", "scaffold_smiles"),
}


CHEM_SYSTEM_PROMPT = """你是顶级化学智能体 ChemAgent。你可以同时调用 RDKit 与 Open Babel 工具。

【核心工作流法则】
1. 采用 ReAct 工作流：先思考，再调用工具，再读取结果，然后继续下一步。
2. 你可以连续调用多个工具；上一个工具的输出就是下一个工具的输入依据。
3. 当前全局最新 SMILES 是：{active_smiles}
4. 如果调用了 `tool_strip_salts`、`tool_murcko_scaffold`、`tool_validate_smiles` 或 `tool_pubchem_lookup` 并拿到了新的 SMILES，下一个工具必须优先使用这个新 SMILES，绝不能回退到用户最初输入的旧 SMILES。
5. 如果不确定下一步该使用哪个 SMILES，请优先使用当前状态中的 `active_smiles`。
6. 如果需要生成 3D 构象、PDBQT、MOL2 等 Open Babel 结果，优先确保使用的是干净、可用的 SMILES。
7. 绝不要编造工具结果；所有结论都必须基于现有消息与工具返回。

【HITL 硬约束】
1. `tool_ask_human` 是“终止式控制工具”，不是普通数据工具。
2. 一旦决定调用 `tool_ask_human`，本轮 `tool_calls` 数量必须严格等于 1。
3. `tool_ask_human` 绝不能与 `tool_pubchem_lookup`、`tool_web_search`、RDKit、Open Babel 或任何其他工具同轮混用。
4. 调用 `tool_ask_human` 前，先完成你当前轮次里已经拿到的工具结果分析；如果还缺关键用户信息，再单独发起这一轮澄清。
5. 澄清问题必须只有一个，且必须具体，不能把多个问题打包在一起。

【特殊任务指南】
- 如果用户要求计算理化性质、Lipinski、QED、TPSA、相似度、骨架、子结构，使用 RDKit 相关工具。
- 如果用户要求格式转换、3D 构象、PDBQT、部分电荷、Open Babel 交叉验证，使用 Open Babel 相关工具。
- 如果用户要求在图上高亮某个骨架或子结构，先用 `tool_substructure_match` 获取 `match_atoms`，再将它们作为 `highlight_atoms` 传给 `tool_render_smiles`。
- 如果只有化合物名称而没有 SMILES，可先使用 `tool_pubchem_lookup`。
- 如果信息不足且确实无法继续，再单独使用 `tool_ask_human` 开启澄清轮次。
- 不允许输出“先查一下再顺便 ask_human”这类混合工具计划；`tool_ask_human` 与其他工具必须分成不同轮次。

【输出要求】
- 工具调用完成后，用中文给出清晰、专业、简洁的最终回答。
- 当已经有足够信息时，不要继续调用工具。
- 当 `tool_ask_human` 恢复后，你会在其工具结果里看到用户澄清答案字段 `answer`，把它当作最新用户补充信息继续研究。

【任务清单】
{task_plan}
"""


TaskStatus = Literal["pending", "in_progress", "completed", "failed"]


class Task(TypedDict):
    id: str
    description: str
    status: TaskStatus


class ChemState(TypedDict):
    """Unified graph state for the chem ReAct agent."""
    messages: Annotated[list[BaseMessage], add_messages]
    active_smiles: str | None
    artifacts: Annotated[list[dict], operator.add]
    tasks: list[Task]
    is_complex: bool


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_complex: bool = Field(
        description="任务是否包含多个子目标、明显的顺序依赖，或通常需要至少三次工具调用。",
    )


class PlannedTaskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="单个可执行子任务，要求具体明确。")


class PlanStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[PlannedTaskItem] = Field(description="按顺序排列的 3-5 个子任务。")


ToolResult = dict[str, Any]
ToolPostprocessor = Callable[[ToolResult, dict[str, Any], list[dict], RunnableConfig], Awaitable[ToolResult]]


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


def _format_tasks_for_prompt(tasks: list[Task] | None) -> str:
    if not tasks:
        return "- 当前没有显式任务清单；直接根据用户请求执行即可，无需调用 `tool_update_task_status`。"

    lines = [
        "- 你必须按顺序执行以下任务。",
        "- 开始某项任务前，先调用 `tool_update_task_status(task_id, \"in_progress\")`。",
        "- 完成某项任务后，立即调用 `tool_update_task_status(task_id, \"completed\")`。",
        "- 如果某项任务无法完成，调用 `tool_update_task_status(task_id, \"failed\")` 并说明原因。",
    ]
    for task in tasks:
        lines.append(f"- [{task['status']}] {task['id']}. {task['description']}")
    return "\n".join(lines)


def _normalize_tasks(raw_tasks: list[PlannedTaskItem]) -> list[Task]:
    descriptions = [item.description.strip() for item in raw_tasks if item.description.strip()]
    normalized = descriptions[:5]
    if not normalized:
        normalized = ["分析用户请求并给出可执行结论"]
    return [
        {
            "id": str(index),
            "description": description,
            "status": "pending",
        }
        for index, description in enumerate(normalized, start=1)
    ]


def _update_tasks(tasks: list[Task], task_id: str, status: TaskStatus) -> tuple[list[Task], Task | None]:
    updated: list[Task] = []
    matched_task: Task | None = None

    for task in tasks:
        next_task = dict(task)
        if status == "in_progress" and next_task["status"] == "in_progress" and next_task["id"] != task_id:
            next_task["status"] = "pending"

        if next_task["id"] == task_id:
            next_task["status"] = status
            matched_task = next_task

        updated.append(next_task)

    return updated, matched_task


async def _dispatch_task_update(tasks: list[Task], config: RunnableConfig, source: str) -> None:
    await adispatch_custom_event(
        "task_update",
        {
            "tasks": tasks,
            "source": source,
        },
        config=config,
    )


def _refresh_result(
    parsed: ToolResult,
    *,
    required_key: str,
    loader: Callable[[], ToolResult],
) -> ToolResult:
    return parsed if parsed.get(required_key) else loader()


def _apply_active_smiles_update(
    tool_name: str,
    parsed: ToolResult,
    current_smiles: str | None,
) -> str | None:
    update_rule = _ACTIVE_SMILES_UPDATES.get(tool_name)
    if update_rule is None:
        return current_smiles

    status_key, smiles_key = update_rule
    return parsed.get(smiles_key) or current_smiles if parsed.get(status_key) else current_smiles


async def _dispatch_artifact(artifacts: list[dict], artifact: dict, config: RunnableConfig) -> None:
    artifacts.append(artifact)
    await adispatch_custom_event("artifact", artifact, config=config)


async def _postprocess_render_smiles(
    parsed: ToolResult,
    _args: dict[str, Any],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    if parsed.get("is_valid") and parsed.get("image"):
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "molecule_image",
                "title": "2D 分子结构图",
                "smiles": parsed.get("smiles"),
                "image": parsed.get("image"),
                "highlight_atoms": parsed.get("highlight_atoms", []),
            },
            config,
        )
        return {
            "status": "success",
            "message": "2D结构图已发送给用户",
            "smiles": parsed.get("smiles"),
            "highlight_atoms": parsed.get("highlight_atoms", []),
        }
    return parsed


async def _postprocess_descriptors(
    parsed: ToolResult,
    args: dict[str, Any],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    detailed = _refresh_result(
        parsed,
        required_key="structure_image",
        loader=lambda: compute_descriptors(args.get("smiles", ""), args.get("name", "")),
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
        summary = _strip_binary_fields(detailed)
        summary["message"] = "描述符结果已生成，结构图已发送给用户"
        return summary
    return detailed


async def _postprocess_substructure_match(
    parsed: ToolResult,
    args: dict[str, Any],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    detailed = _refresh_result(
        parsed,
        required_key="highlighted_image",
        loader=lambda: substructure_match(args.get("smiles", ""), args.get("smarts_pattern", "")),
    )
    if detailed.get("highlighted_image"):
        await _dispatch_artifact(
            artifacts,
            {
                "kind": "highlighted_substructure",
                "title": "子结构高亮图",
                "smiles": detailed.get("smiles"),
                "image": detailed.get("highlighted_image"),
                "match_atoms": detailed.get("match_atoms", []),
            },
            config,
        )
        summary = _strip_binary_fields(detailed)
        summary["message"] = "子结构匹配完成，高亮图已发送给用户"
        return summary
    return detailed


async def _postprocess_build_3d_conformer(
    parsed: ToolResult,
    args: dict[str, Any],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    detailed = _refresh_result(
        parsed,
        required_key="sdf_content",
        loader=lambda: build_3d_conformer(
            args.get("smiles", ""),
            name=args.get("name", ""),
            forcefield=args.get("forcefield", "mmff94"),
            steps=args.get("steps", 500),
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
        summary = _strip_binary_fields(detailed)
        summary["message"] = "3D构象已生成，SDF 文件已发送给用户"
        return summary
    return detailed


async def _postprocess_prepare_pdbqt(
    parsed: ToolResult,
    args: dict[str, Any],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    detailed = _refresh_result(
        parsed,
        required_key="pdbqt_content",
        loader=lambda: prepare_pdbqt(
            args.get("smiles", ""),
            name=args.get("name", ""),
            ph=args.get("ph", 7.4),
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
        summary = _strip_binary_fields(detailed)
        summary["message"] = "PDBQT 文件已生成并发送给用户"
        return summary
    return detailed


async def _postprocess_convert_format(
    parsed: ToolResult,
    args: dict[str, Any],
    artifacts: list[dict],
    config: RunnableConfig,
) -> ToolResult:
    detailed = parsed
    if len(str(detailed.get("output", ""))) >= 500:
        detailed = convert_format(
            args.get("molecule_str", ""),
            args.get("input_fmt", ""),
            args.get("output_fmt", ""),
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


_TOOL_POSTPROCESSORS: dict[str, ToolPostprocessor] = {
    "tool_render_smiles": _postprocess_render_smiles,
    "tool_compute_descriptors": _postprocess_descriptors,
    "tool_substructure_match": _postprocess_substructure_match,
    "tool_build_3d_conformer": _postprocess_build_3d_conformer,
    "tool_prepare_pdbqt": _postprocess_prepare_pdbqt,
    "tool_convert_format": _postprocess_convert_format,
}

_TOOL_LOOKUP = {tool.name: tool for tool in ALL_CHEM_TOOLS}


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

async def task_router_node(state: ChemState, config: RunnableConfig) -> dict:
    """Fast intent classifier that decides whether explicit planning is needed."""
    last_user_message = next(
        (
            str(message.content)
            for message in reversed(state["messages"])
            if isinstance(message, HumanMessage)
        ),
        "",
    )

    llm = _build_llm(RouteDecision)
    decision = await llm.ainvoke([
        SystemMessage(
            content=(
                "你是 ChemAgent 的任务路由器。"
                "如果用户请求包含多个子目标、明确的先后依赖、跨来源调研，"
                "或者通常需要至少三次工具调用，返回 is_complex=true；否则返回 false。"
            )
        ),
        HumanMessage(content=last_user_message),
    ])

    is_complex = bool(decision.is_complex)
    if not is_complex and state.get("tasks"):
        await _dispatch_task_update([], config, source="task_router")

    return {
        "is_complex": is_complex,
        "tasks": [] if not is_complex else state.get("tasks", []),
    }


async def planner_node(state: ChemState, config: RunnableConfig) -> dict:
    """Decompose a complex request into a compact executable task list."""
    llm = _build_llm(PlanStructure)
    plan = await llm.ainvoke([
        SystemMessage(
            content=(
                "你是 ChemAgent 的化学任务规划师。"
                "请把复杂请求拆解为 3-5 个按顺序执行的子任务。"
                "每个任务必须具体、可执行，不要把“输出最终回答”本身当作任务。"
            )
        ),
        *state["messages"],
    ])

    tasks = _normalize_tasks(plan.tasks)
    await _dispatch_task_update(tasks, config, source="planner_node")
    return {
        "tasks": tasks,
        "is_complex": True,
    }

async def chem_agent_node(state: ChemState) -> dict:
    """Unified reasoning node that decides whether to call tools or answer."""
    llm = _build_llm()
    llm_with_tools = llm.bind_tools(ALL_CHEM_TOOLS)

    response = await llm_with_tools.ainvoke([
        SystemMessage(
            content=CHEM_SYSTEM_PROMPT.format(
                active_smiles=_current_smiles_text(state.get("active_smiles")),
                task_plan=_format_tasks_for_prompt(state.get("tasks")),
            )
        ),
        *state["messages"],
    ])
    return {"messages": [response]}


async def tools_executor_node(state: ChemState, config: RunnableConfig) -> dict:
    """Execute tool calls, dispatch artifacts, and update explicit state."""
    last_message = state["messages"][-1]
    new_active_smiles = state.get("active_smiles")
    new_tasks = [dict(task) for task in state.get("tasks", [])]
    artifacts: list[dict] = []
    tool_messages: list[ToolMessage] = []
    tool_calls = list(getattr(last_message, "tool_calls", []))

    ask_human_call = next((tool_call for tool_call in tool_calls if tool_call["name"] == "tool_ask_human"), None)
    if ask_human_call is not None:
        args = ask_human_call.get("args", {})
        resume_value = interrupt(
            {
                "question": str(args.get("question", "")),
                "options": list(args.get("options", [])),
                "called_tools": [
                    tool_call["name"]
                    for tool_call in tool_calls
                    if tool_call["name"] != "tool_ask_human"
                ],
                "known_smiles": new_active_smiles,
            }
        )

        if isinstance(resume_value, dict):
            answer = str(
                resume_value.get("answer")
                or resume_value.get("content")
                or resume_value
            )
        else:
            answer = str(resume_value)

        tool_messages.append(
            ToolMessage(
                content=json.dumps(
                    {
                        "status": "clarification_received",
                        "message": "用户已提供澄清信息",
                        "question": str(args.get("question", "")),
                        "answer": answer.strip(),
                        "options": list(args.get("options", [])),
                    },
                    ensure_ascii=False,
                ),
                tool_call_id=ask_human_call.get("id", ""),
                name="tool_ask_human",
            )
        )
        return {
            "messages": tool_messages,
            "active_smiles": new_active_smiles,
            "artifacts": artifacts,
            "tasks": new_tasks,
        }

    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_call_id = tool_call.get("id", "")
        args = tool_call.get("args", {})
        tool = _TOOL_LOOKUP.get(tool_name)

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
                if tool_name == "tool_update_task_status":
                    requested_task_id = str(parsed.get("task_id", "")).strip()
                    requested_status = str(parsed.get("task_status", "")).strip()

                    if requested_status in {"in_progress", "completed", "failed"}:
                        new_tasks, updated_task = _update_tasks(new_tasks, requested_task_id, requested_status)
                        if updated_task is None:
                            parsed = {
                                "status": "error",
                                "error": f"Task {requested_task_id} not found in current plan",
                                "known_task_ids": [task["id"] for task in new_tasks],
                            }
                        else:
                            await _dispatch_task_update(new_tasks, config, source="tools_executor")
                            parsed = {
                                "status": "success",
                                "task_id": updated_task["id"],
                                "task_status": updated_task["status"],
                                "description": updated_task["description"],
                            }
                    else:
                        parsed = {
                            "status": "error",
                            "error": f"Unsupported task status: {requested_status}",
                        }
                else:
                    new_active_smiles = _apply_active_smiles_update(tool_name, parsed, new_active_smiles)
                    postprocessor = _TOOL_POSTPROCESSORS.get(tool_name)
                    if postprocessor is not None:
                        parsed = await postprocessor(parsed, args, artifacts, config)

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
        "tasks": new_tasks,
    }


# ── Graph Construction ────────────────────────────────────────────────────────

def build_graph(checkpointer: Any | None = None) -> Any:
    """Build the unified chem ReAct graph."""
    graph = StateGraph(ChemState)

    graph.add_node("task_router", task_router_node)
    graph.add_node("planner_node", planner_node)
    graph.add_node("chem_agent", chem_agent_node)
    graph.add_node("tools_executor", tools_executor_node)

    graph.add_edge(START, "task_router")

    def route_from_router(state: ChemState) -> str:
        return "planner_node" if state.get("is_complex") else "chem_agent"

    graph.add_conditional_edges(
        "task_router",
        route_from_router,
        {
            "planner_node": "planner_node",
            "chem_agent": "chem_agent",
        }
    )

    graph.add_edge("planner_node", "chem_agent")

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

    return graph.compile(checkpointer=checkpointer)


# ── Export ────────────────────────────────────────────────────────────────────

graph: Any = build_graph()
compiled_graph: Any = graph  # Backward compatibility


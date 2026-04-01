from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from app.agents.config import build_llm_config
from app.agents.state import PlannedTaskItem, Task, TaskStatus


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
- 工具调用完成后，与用户保持同一语种，给出清晰、专业、简洁的最终回答。
- 当已经有足够信息时，不要继续调用工具。
- 当 `tool_ask_human` 恢复后，你会在其工具结果里看到用户澄清答案字段 `answer`，把它当作最新用户补充信息继续研究。

【任务清单】
{task_plan}
"""

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

ToolResult = dict[str, Any]
ToolPostprocessor = Callable[[ToolResult, dict[str, Any], list[dict], RunnableConfig], Awaitable[ToolResult]]
_TASK_MAX_LENGTH = 16
_TASK_SPLIT_RE = re.compile(r"[，,；;。:：(（\[]")


def _condense_task_description(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" -•\t\r\n'\"“”‘’")
    if not cleaned:
        return ""

    condensed = _TASK_SPLIT_RE.split(cleaned, maxsplit=1)[0].strip()
    condensed = re.sub(r"^(步骤\s*\d+|第\s*\d+\s*步)\s*[:：.-]?\s*", "", condensed)
    condensed = condensed.strip(" -•\t\r\n'\"“”‘’")

    if len(condensed) > _TASK_MAX_LENGTH:
        condensed = condensed[:_TASK_MAX_LENGTH].rstrip() + "…"

    return condensed


def strip_binary_fields(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in _STRIP_LLM_FIELDS}


def tool_result_to_text(result: dict) -> str:
    cleaned = strip_binary_fields(result)
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


def parse_tool_output(output: Any) -> dict[str, Any] | None:
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def current_smiles_text(active_smiles: str | None) -> str:
    return active_smiles or "（无）"


def format_tasks_for_prompt(tasks: list[Task] | None) -> str:
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


def normalize_tasks(raw_tasks: list[PlannedTaskItem]) -> list[Task]:
    descriptions = []
    for item in raw_tasks:
        condensed = _condense_task_description(item.description)
        if condensed:
            descriptions.append(condensed)

    normalized = descriptions[:5]
    if not normalized:
        normalized = ["分析请求"]
    return [
        {
            "id": str(index),
            "description": description,
            "status": "pending",
        }
        for index, description in enumerate(normalized, start=1)
    ]


def update_tasks(tasks: list[Task], task_id: str, status: TaskStatus) -> tuple[list[Task], Task | None]:
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


async def dispatch_task_update(tasks: list[Task], config: RunnableConfig, source: str) -> None:
    await adispatch_custom_event(
        "task_update",
        {
            "tasks": tasks,
            "source": source,
        },
        config=config,
    )


def refresh_result(
    parsed: ToolResult,
    *,
    required_key: str,
    loader: Callable[[], ToolResult],
) -> ToolResult:
    return parsed if parsed.get(required_key) else loader()


def apply_active_smiles_update(
    tool_name: str,
    parsed: ToolResult,
    current_smiles: str | None,
) -> str | None:
    update_rule = _ACTIVE_SMILES_UPDATES.get(tool_name)
    if update_rule is None:
        return current_smiles

    status_key, smiles_key = update_rule
    return parsed.get(smiles_key) or current_smiles if parsed.get(status_key) else current_smiles


def build_llm(structured_schema: type | None = None) -> Any:
    config_dict = build_llm_config()
    config = config_dict["config_list"][0]

    llm = ChatOpenAI(**config)
    if structured_schema:
        llm = llm.with_structured_output(structured_schema)
    return llm
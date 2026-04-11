from __future__ import annotations

import re

from app.agents.state import Task


_STAGE_PATTERNS = (
    re.compile(r"^\s*\*\*阶段\s*(\d+)\s*[:：]\s*(.+?)\*\*\s*$", re.MULTILINE),
    re.compile(r"^\s*##\s*阶段\s*(\d+)\s*[:：]?\s*(.+?)\s*$", re.MULTILINE),
    re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$", re.MULTILINE),
)


def extract_plan_tasks(plan_content: str) -> list[Task]:
    text = str(plan_content or "").strip()
    if not text:
        return []

    seen: set[str] = set()
    tasks: list[Task] = []
    for pattern in _STAGE_PATTERNS:
        for match in pattern.finditer(text):
            task_id = str(match.group(1)).strip()
            description = re.sub(r"\s+", " ", str(match.group(2) or "")).strip(" *\t\n\r")
            if not task_id or not description or task_id in seen:
                continue
            seen.add(task_id)
            tasks.append({
                "id": task_id,
                "description": description[:80],
                "status": "pending",
            })
    return tasks


def has_unfinished_tasks(tasks: list[Task] | None) -> bool:
    return any(str(task.get("status") or "pending") != "completed" for task in (tasks or []))


def build_strict_execution_context(*, plan_id: str, plan_file_ref: str, plan_content: str) -> str:
    return (
        "<execution_context>\n"
        "你当前处于 GENERAL 模式，正在执行已获用户最高审批通过的正式计划。\n"
        f"当前计划 ID: {plan_id}\n"
        f"当前计划文件: {plan_file_ref}\n"
        "</execution_context>\n\n"
        "<approved_plan_content>\n"
        f"{plan_content.strip()}\n"
        "</approved_plan_content>\n\n"
        "<strict_execution_directives>\n"
        "作为核心执行引擎，你必须严格遵守以下自主运行纪律：\n"
        "1. 一气呵成：你已被授权自主执行该计划的所有阶段。绝对禁止在每个阶段完成后停下来询问用户是否继续、是否确认或是否同意委派。\n"
        "2. 禁止对话式汇报：不要输出‘我将先完成阶段1’‘下面进入阶段2’之类的过程性废话。你的首选输出应当是工具调用。\n"
        "3. 闭环委派：若某个阶段需要委派子智能体，直接调用 tool_run_sub_agent。拿到结果后立即分析并自动推进下一阶段。\n"
        "4. 终点条件：只有当计划全部阶段落地，或遇到穷尽重试后仍无法解决的硬性生化错误时，你才允许停止并做最终汇报。\n"
        "5. 状态锚定：每完成计划中的一个阶段，你必须调用 tool_update_task_status 将该阶段标记为 completed；若阶段失败则标记为 failed。只要仍有未完成阶段，就不要停止执行循环。\n"
        "</strict_execution_directives>"
    )


def build_execution_start_instruction() -> str:
    return "开始执行这份已批准计划。不要请求用户确认中间阶段，直接推进直到全部阶段完成或明确失败。"


def build_execution_stop_intercept() -> str:
    return (
        "[System Intercept]\n"
        "检测到你试图停止执行并向用户做过程性汇报。\n"
        "系统已拒绝你的暂停请求。\n"
        "当前计划尚未执行完毕。请立即根据已批准计划调用相应工具，继续推进下一阶段。\n"
        "不要询问用户是否继续，不要输出阶段性请示。"
    )


def extract_execution_context_block(text: str) -> str:
    raw = str(text or "")
    if "<execution_context>" not in raw or "<strict_execution_directives>" not in raw:
        return ""
    return raw.strip()
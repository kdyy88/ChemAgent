from __future__ import annotations

import logging

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import ChemState, PlanStructure
from app.agents.utils import build_llm, dispatch_task_update, normalize_tasks

logger = logging.getLogger(__name__)


async def planner_node(state: ChemState, config: RunnableConfig) -> dict:
    llm = build_llm(PlanStructure, model=state.get("selected_model"))
    plan = await llm.ainvoke([
        SystemMessage(
            content=(
                "你是 ChemAgent 的化学任务规划师。"
                "请把复杂请求拆解为 3-5 个按顺序执行的子任务。"
                "每个任务必须具体、可执行，不要把“输出最终回答”本身当作任务。"
                "任务描述只允许写成简短概括性标签，不要写成长句、原因、参数、括号说明或实现细节。"
                "每项尽量控制在 4-12 个中文字符，最长不要超过 16 个字符。"
                "优先使用类似“读取SMILES”“盐脱除”“生成3D构象”“优化构象”“导出SDF”这样的短短语。"
            )
        ),
        *state["messages"],
    ])

    tasks = normalize_tasks(plan.tasks)
    logger.info(
        "📋 [Planner] generated %d tasks: %s",
        len(tasks),
        [t.get("description", "")[:30] for t in tasks],
    )
    await dispatch_task_update(tasks, config, source="planner_node")
    return {
        "tasks": tasks,
        "is_complex": True,
    }
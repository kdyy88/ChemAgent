from __future__ import annotations

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import ChemState, PlanStructure
from app.agents.utils import build_llm, dispatch_task_update, normalize_tasks


async def planner_node(state: ChemState, config: RunnableConfig) -> dict:
    llm = build_llm(PlanStructure)
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

    tasks = normalize_tasks(plan.tasks)
    await dispatch_task_update(tasks, config, source="planner_node")
    return {
        "tasks": tasks,
        "is_complex": True,
    }
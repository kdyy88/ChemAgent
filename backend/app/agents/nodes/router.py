from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import ChemState, RouteDecision
from app.agents.utils import build_llm, dispatch_task_update

logger = logging.getLogger(__name__)


async def task_router_node(state: ChemState, config: RunnableConfig) -> dict:
    last_user_message = next(
        (
            str(message.content)
            for message in reversed(state["messages"])
            if isinstance(message, HumanMessage)
        ),
        "",
    )

    llm = build_llm(RouteDecision, model=state.get("selected_model"))
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
    logger.info(
        "🔀 [TaskRouter] is_complex=%s  query_preview=%.80s",
        is_complex,
        last_user_message,
    )
    if not is_complex and state.get("tasks"):
        await dispatch_task_update([], config, source="task_router")

    return {
        "is_complex": is_complex,
        "tasks": [] if not is_complex else state.get("tasks", []),
    }


def route_from_router(state: ChemState) -> str:
    return "planner_node" if state.get("is_complex") else "chem_agent"
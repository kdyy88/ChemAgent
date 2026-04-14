from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.domain.schemas.agent import ChemState, RouteDecision
from app.agents.utils import build_llm, dispatch_task_update

logger = logging.getLogger(__name__)


_SCAFFOLD_HOP_HINTS = (
    "scaffold hop",
    "scaffold-hop",
    "scaffold",
    "骨架跃迁",
    "新骨架",
)
_IBRUTINIB_HINTS = ("ibrutinib", "伊布替尼")
_WARHEAD_HINTS = ("acrylamide", "warhead", "丙烯酰胺")
_INDOLE_HINTS = ("fused indole", "并环吲哚", "indole", "吲哚")


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _mentions_three_candidates(text: str) -> bool:
    return bool(re.search(r"\b3\b", text)) or "3个" in text or "三个" in text


def _is_scaffold_hop_mvp_request(text: str) -> bool:
    normalized = text.casefold()
    return (
        _contains_any(normalized, _IBRUTINIB_HINTS)
        and _contains_any(normalized, _WARHEAD_HINTS)
        and _contains_any(normalized, _INDOLE_HINTS)
        and (_contains_any(normalized, _SCAFFOLD_HOP_HINTS) or "候选" in normalized)
        and _mentions_three_candidates(normalized)
    )


async def task_router_node(state: ChemState, config: RunnableConfig) -> dict:
    last_user_message = next(
        (
            str(message.content)
            for message in reversed(state["messages"])
            if isinstance(message, HumanMessage)
        ),
        "",
    )

    if _is_scaffold_hop_mvp_request(last_user_message):
        logger.info("🧭 [TaskRouter] matched scaffold_hop_mvp scenario")
        return {
            "is_complex": True,
            "scenario_kind": "scaffold_hop_mvp",
            "candidate_handles": ["candidate_1", "candidate_2", "candidate_3"],
            "active_handle": "root_molecule",
            "tasks": state.get("tasks", []),
        }

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
        "scenario_kind": state.get("scenario_kind"),
        "tasks": [] if not is_complex else state.get("tasks", []),
    }


def route_from_router(state: ChemState) -> str:
    return "planner_node" if state.get("is_complex") else "chem_agent"
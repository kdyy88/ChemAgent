from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    chem_agent_node,
    memory_consolidation_node,
    planner_node,
    route_from_agent,
    route_from_router,
    task_router_node,
    tools_executor_node,
)
from app.domain.schemas.agent import ChemState


def build_graph(checkpointer: Any | None = None) -> Any:
    graph = StateGraph(ChemState)

    graph.add_node("task_router", task_router_node)
    graph.add_node("planner_node", planner_node)
    graph.add_node("chem_agent", chem_agent_node)
    graph.add_node("tools_executor", tools_executor_node)
    graph.add_node("memory_consolidation", memory_consolidation_node)

    graph.add_edge(START, "task_router")
    graph.add_conditional_edges(
        "task_router",
        route_from_router,
        {
            "planner_node": "planner_node",
            "chem_agent": "chem_agent",
        },
    )
    graph.add_edge("planner_node", "chem_agent")
    graph.add_conditional_edges(
        "chem_agent",
        route_from_agent,
        {
            "tools_executor": "tools_executor",
            "__end__": "memory_consolidation",
        },
    )
    graph.add_edge("tools_executor", "chem_agent")
    graph.add_edge("memory_consolidation", END)

    return graph.compile(checkpointer=checkpointer)


graph: Any = build_graph()
compiled_graph: Any = graph
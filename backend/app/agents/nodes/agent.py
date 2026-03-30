from __future__ import annotations

from langchain_core.messages import SystemMessage

from app.agents.lg_tools import ALL_CHEM_TOOLS
from app.agents.state import ChemState
from app.agents.utils import CHEM_SYSTEM_PROMPT, build_llm, current_smiles_text, format_tasks_for_prompt


async def chem_agent_node(state: ChemState) -> dict:
    llm = build_llm()
    llm_with_tools = llm.bind_tools(ALL_CHEM_TOOLS)

    response = await llm_with_tools.ainvoke([
        SystemMessage(
            content=CHEM_SYSTEM_PROMPT.format(
                active_smiles=current_smiles_text(state.get("active_smiles")),
                task_plan=format_tasks_for_prompt(state.get("tasks")),
            )
        ),
        *state["messages"],
    ])
    return {"messages": [response]}


def route_from_agent(state: ChemState) -> str:
    last_message = state["messages"][-1]
    return "tools_executor" if getattr(last_message, "tool_calls", None) else "__end__"
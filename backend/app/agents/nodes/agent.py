from __future__ import annotations

import logging

from langchain_core.messages import SystemMessage

logger = logging.getLogger(__name__)

from app.agents.lg_tools import ALL_CHEM_TOOLS
from app.agents.state import ChemState
from app.agents.utils import CHEM_SYSTEM_PROMPT, build_llm, current_smiles_text, format_tasks_for_prompt, normalize_messages_for_api


async def chem_agent_node(state: ChemState) -> dict:
    llm = build_llm()
    llm_with_tools = llm.bind_tools(ALL_CHEM_TOOLS)

    # ⚡ JIT normalization: fix any broken message sequences (e.g. dangling
    # tool_calls left by a user-interrupted request) in memory before the API
    # call.  The sanitized list is never written back to the checkpointer, so
    # SQLite retains the original history with zero extra I/O.
    safe_messages = normalize_messages_for_api(state["messages"])

    response = await llm_with_tools.ainvoke([
        SystemMessage(
            content=CHEM_SYSTEM_PROMPT.format(
                active_smiles=current_smiles_text(state.get("active_smiles")),
                task_plan=format_tasks_for_prompt(state.get("tasks")),
            )
        ),
        *safe_messages,
    ])

    if hasattr(response, "usage_metadata") and response.usage_metadata:
        in_tok = response.usage_metadata.get("input_tokens", 0)
        total_tok = response.usage_metadata.get("total_tokens", 0)
        logger.info("📊 [Context Monitor] input=%d total=%d", in_tok, total_tok)
        if total_tok > 100_000:
            logger.warning("🚨 [Context Monitor] Approaching context limit (total=%d)", total_tok)

    return {"messages": [response]}


def route_from_agent(state: ChemState) -> str:
    last_message = state["messages"][-1]
    return "tools_executor" if getattr(last_message, "tool_calls", None) else "__end__"
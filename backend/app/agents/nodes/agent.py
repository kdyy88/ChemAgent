from __future__ import annotations

import logging
import os

from langchain_core.messages import SystemMessage

logger = logging.getLogger(__name__)

from app.agents.lg_tools import ALL_CHEM_TOOLS
from app.agents.prompts import get_system_prompt
from app.agents.state import ChemState
from app.agents.config import get_active_model_name, is_native_reasoning_model, _load_environment
from app.agents.utils import build_llm, format_tasks_for_prompt, normalize_messages_for_api

# Loaded lazily so dotenv is applied before the flag is read.
_load_environment()
# Set CHEMAGENT_LOG_LLM_IO=1 (in .env or shell) to log full LLM prompt / response at INFO level.
_LOG_LLM_IO = os.environ.get("CHEMAGENT_LOG_LLM_IO", "").strip().lower() in {"1", "true", "yes", "on"}


async def chem_agent_node(state: ChemState) -> dict:
    llm = build_llm()
    llm_with_tools = llm.bind_tools(ALL_CHEM_TOOLS)

    # ⚡ JIT normalization: fix any broken message sequences (e.g. dangling
    # tool_calls left by a user-interrupted request) in memory before the API
    # call.  The sanitized list is never written back to the checkpointer, so
    # SQLite retains the original history with zero extra I/O.
    safe_messages = normalize_messages_for_api(state["messages"])

    # Derive active artifact ID from the most recent artifact in state.
    artifacts = state.get("artifacts") or []
    active_artifact_id = artifacts[-1].get("artifact_id") if artifacts else None

    env_info = {
        "active_smiles": state.get("active_smiles"),
        "active_artifact_id": active_artifact_id,
        "task_plan": format_tasks_for_prompt(state.get("tasks")),
        "model_name": get_active_model_name(),
        "is_native_reasoning_model": is_native_reasoning_model(get_active_model_name()),
    }

    prompt_messages = [
        SystemMessage(content=get_system_prompt(env_info)),
        *safe_messages,
    ]

    if _LOG_LLM_IO:
        for i, msg in enumerate(prompt_messages):
            role = getattr(msg, "type", type(msg).__name__)
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            logger.info("📨 [LLM Input] msg[%d] role=%s:\n%s", i, role, content)

    response = await llm_with_tools.ainvoke(prompt_messages)

    if _LOG_LLM_IO:
        # Log text content
        resp_text = response.content if isinstance(response.content, str) else str(response.content)
        logger.info("📩 [LLM Output] content:\n%s", resp_text)
        # Log tool calls if present
        if getattr(response, "tool_calls", None):
            for tc in response.tool_calls:
                logger.info("🔧 [LLM Output] tool_call: %s args=%s", tc.get("name"), tc.get("args"))
        # Log reasoning / thinking content if present (native reasoning models)
        thinking = None
        if hasattr(response, "additional_kwargs"):
            thinking = response.additional_kwargs.get("reasoning") or response.additional_kwargs.get("thinking")
        if thinking:
            logger.info("🧠 [LLM Reasoning]:\n%s", thinking)

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
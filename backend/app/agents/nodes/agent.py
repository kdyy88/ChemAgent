from __future__ import annotations

import logging
import os
import re

from langchain_core.messages import SystemMessage

logger = logging.getLogger(__name__)

from app.agents.lg_tools import ALL_CHEM_TOOLS
from app.agents.prompts import get_system_prompt
from app.agents.state import ChemState
from app.agents.config import get_active_model_name, is_native_reasoning_model, _load_environment
from app.agents.utils import build_llm, format_tasks_for_prompt, normalize_messages_for_api, sanitize_messages_for_state
from app.agents.utils import format_molecule_workspace_for_prompt
from app.core.artifact_store import get_engine_artifact_warning

# Loaded lazily so dotenv is applied before the flag is read.
_load_environment()
# Set CHEMAGENT_LOG_LLM_IO=1 to log compact prompt/response summaries.
# Set CHEMAGENT_LOG_LLM_IO_FULL=1 to dump full prompt/response bodies.
_LOG_LLM_IO = os.environ.get("CHEMAGENT_LOG_LLM_IO", "").strip().lower() in {"1", "true", "yes", "on"}
_LOG_LLM_IO_FULL = os.environ.get("CHEMAGENT_LOG_LLM_IO_FULL", "").strip().lower() in {"1", "true", "yes", "on"}


def _preview_text(value: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", (value or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + " ...[truncated]"


def _log_prompt_summary(prompt_messages: list[SystemMessage]) -> None:
    role_counts: dict[str, int] = {}
    total_chars = 0
    preview_lines: list[str] = []

    for index, msg in enumerate(prompt_messages):
        role = getattr(msg, "type", type(msg).__name__)
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        role_counts[role] = role_counts.get(role, 0) + 1
        total_chars += len(content)

        if index == 0 or index >= len(prompt_messages) - 4:
            preview_lines.append(
                f"msg[{index}] role={role} chars={len(content)} preview={_preview_text(content)}"
            )

    logger.info(
        "📨 [LLM Input Summary] messages=%d total_chars=%d roles=%s\n%s",
        len(prompt_messages),
        total_chars,
        role_counts,
        "\n".join(preview_lines),
    )


def _log_response_summary(response: object) -> None:
    resp_text = response.content if isinstance(response.content, str) else str(response.content)
    tool_calls = list(getattr(response, "tool_calls", None) or [])
    logger.info(
        "📩 [LLM Output Summary] chars=%d tool_calls=%d preview=%s",
        len(resp_text),
        len(tool_calls),
        _preview_text(resp_text),
    )


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
    artifact_warning = await get_engine_artifact_warning(str(active_artifact_id or "").strip())

    env_info = {
        "active_smiles": state.get("active_smiles"),
        "active_artifact_id": active_artifact_id,
        "artifact_warning": artifact_warning,
        "molecule_workspace_summary": format_molecule_workspace_for_prompt(
            state.get("molecule_workspace"),
            state.get("active_smiles"),
        ),
        "task_plan": format_tasks_for_prompt(state.get("tasks")),
        "model_name": get_active_model_name(),
        "is_native_reasoning_model": is_native_reasoning_model(get_active_model_name()),
    }

    prompt_messages = [
        SystemMessage(content=get_system_prompt(env_info)),
        *safe_messages,
    ]

    if _LOG_LLM_IO and not _LOG_LLM_IO_FULL:
        _log_prompt_summary(prompt_messages)
    elif _LOG_LLM_IO_FULL:
        for i, msg in enumerate(prompt_messages):
            role = getattr(msg, "type", type(msg).__name__)
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            logger.info("📨 [LLM Input] msg[%d] role=%s:\n%s", i, role, content)

    response = await llm_with_tools.ainvoke(prompt_messages)

    if _LOG_LLM_IO and not _LOG_LLM_IO_FULL:
        _log_response_summary(response)
        # Log tool calls if present
        if getattr(response, "tool_calls", None):
            for tc in response.tool_calls:
                logger.info("🔧 [LLM Output] tool_call: %s args=%s", tc.get("name"), tc.get("args"))
    elif _LOG_LLM_IO_FULL:
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

    return {"messages": await sanitize_messages_for_state([response], source="chem_agent")}


def route_from_agent(state: ChemState) -> str:
    last_message = state["messages"][-1]
    return "tools_executor" if getattr(last_message, "tool_calls", None) else "__end__"
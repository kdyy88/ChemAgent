from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

from app.agents.prompts import get_system_prompt
from app.agents.pending_jobs import drain_pending_worker_tasks
from app.domain.schemas.agent import ChemState
from app.tools.registry import get_root_tools
from app.agents.config import get_active_model_name, is_native_reasoning_model, _load_environment
from app.agents.utils import (
    build_llm,
    format_ide_workspace,
    format_workspace_projection,
    format_scratchpad,
    format_tasks_for_prompt,
    normalize_messages_for_api,
    sanitize_messages_for_state,
)
from app.services.workspace import ensure_workspace_projection, project_legacy_workspace_view
from app.skills.loader import load_skill_catalogue

# Loaded lazily so dotenv is applied before the flag is read.
_load_environment()
# Set CHEMAGENT_LOG_LLM_IO=1 to log compact prompt/response summaries.
# Set CHEMAGENT_LOG_LLM_IO_FULL=1 to dump full prompt/response bodies.
_LOG_LLM_IO = os.environ.get("CHEMAGENT_LOG_LLM_IO", "").strip().lower() in {"1", "true", "yes", "on"}
_LOG_LLM_IO_FULL = os.environ.get("CHEMAGENT_LOG_LLM_IO_FULL", "").strip().lower() in {"1", "true", "yes", "on"}

# ── Per-session file logging ──────────────────────────────────────────────────
# Default: <project_root>/logs/sessions/  (four levels up from this file).
# Override with CHEMAGENT_LOG_DIR env var.
_LOG_DIR = Path(
    os.environ.get(
        "CHEMAGENT_LOG_DIR",
        str(Path(__file__).resolve().parents[4] / "logs" / "sessions"),
    )
)

_session_file_handlers: dict[str, logging.FileHandler] = {}


def _get_session_logger(session_id: str) -> logging.Logger:
    """Return (or create) a file-backed Logger for *session_id*.

    Writes to ``<_LOG_DIR>/session_<session_id>.log`` in append mode.
    ``propagate=False`` prevents double-printing to the uvicorn console.
    """
    name = f"chemagent.session.{session_id}"
    slog = logging.getLogger(name)
    if session_id not in _session_file_handlers:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(
            _LOG_DIR / f"session_{session_id}.log",
            mode="a",
            encoding="utf-8",
        )
        fh.setFormatter(
            logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        slog.addHandler(fh)
        slog.setLevel(logging.DEBUG)
        slog.propagate = False
        _session_file_handlers[session_id] = fh
    return slog


def _preview_text(value: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", (value or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + " ...[truncated]"


def _log_prompt_summary(prompt_messages: list[SystemMessage], *logs: logging.Logger) -> None:
    _logs = logs if logs else (logger,)
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

    for _l in _logs:
        _l.info(
            "📨 [LLM Input Summary] messages=%d total_chars=%d roles=%s\n%s",
            len(prompt_messages),
            total_chars,
            role_counts,
            "\n".join(preview_lines),
        )


def _log_response_summary(response: object, *logs: logging.Logger) -> None:
    _logs = logs if logs else (logger,)
    resp_text = response.content if isinstance(response.content, str) else str(response.content)
    tool_calls = list(getattr(response, "tool_calls", None) or [])
    for _l in _logs:
        _l.info(
            "📩 [LLM Output Summary] chars=%d tool_calls=%d preview=%s",
            len(resp_text),
            len(tool_calls),
            _preview_text(resp_text),
        )


async def chem_agent_node(state: ChemState, config: RunnableConfig = None) -> dict:  # type: ignore[assignment]
    selected_model = state.get("selected_model")
    llm = build_llm(model=selected_model)
    llm_with_tools = llm.bind_tools(get_root_tools())

    pending_drain = await drain_pending_worker_tasks(state, config)
    drained_messages = pending_drain["messages"]
    drained_artifacts = pending_drain["artifacts"]
    drained_workspace_events = pending_drain["workspace_events"]
    drained_workspace_projection = pending_drain["workspace_projection"]
    remaining_pending_tasks = pending_drain["pending_worker_tasks"]

    # ⚡ JIT normalization: fix any broken message sequences (e.g. dangling
    # tool_calls left by a user-interrupted request) in memory before the API
    # call.  The sanitized list is never written back to the checkpointer, so
    # SQLite retains the original history with zero extra I/O.
    safe_messages = normalize_messages_for_api(state["messages"])

    # Derive active artifact ID from the most recent artifact in state.
    artifacts = state.get("artifacts") or []
    active_artifact_id = artifacts[-1].get("artifact_id") if artifacts else None
    artifact_warning = state.get("artifact_expiry_warning")

    scratchpad = state.get("scratchpad") or {}
    workspace_projection = drained_workspace_projection or state.get("workspace_projection")
    if workspace_projection:
        workspace = ensure_workspace_projection(
            {
                "workspace_projection": workspace_projection,
                "scratchpad": scratchpad,
            },
            project_id=str((((config or {}).get("configurable") or {}).get("thread_id")) or "default_project"),
        )
        viewport, molecule_tree = project_legacy_workspace_view(workspace)
    else:
        viewport = state.get("viewport") or {"focused_artifact_ids": []}
        molecule_tree = state.get("molecule_tree") or {}

    env_info = {
        "active_artifact_id": active_artifact_id,
        "artifact_warning": artifact_warning,
        "viewport_content": (
            format_workspace_projection(workspace_projection)
            if workspace_projection
            else format_ide_workspace(viewport, molecule_tree)
        ),
        "scratchpad_content": format_scratchpad(scratchpad),
        "task_plan": format_tasks_for_prompt(state.get("tasks")),
        "model_name": get_active_model_name(selected_model),
        "is_native_reasoning_model": is_native_reasoning_model(get_active_model_name(selected_model)),
    }

    # ── Session-scoped file logger ────────────────────────────────────────────
    cfg = (config or {}).get("configurable") or {}
    session_id: str = cfg.get("session_id") or "unknown"
    turn_id: str = cfg.get("turn_id") or "?"

    slog = _get_session_logger(session_id) if (_LOG_LLM_IO or _LOG_LLM_IO_FULL) else None
    _log_targets: tuple[logging.Logger, ...] = (logger, slog) if slog else (logger,)

    if slog:
        slog.info("=" * 72)
        slog.info("TURN %-36s  model=%s", turn_id, get_active_model_name(selected_model))
        slog.info("=" * 72)

    prompt_messages = [
        SystemMessage(content=get_system_prompt(env_info, skill_catalogue=load_skill_catalogue() if state.get("skills_enabled", False) else [])),
        *safe_messages,
        *drained_messages,
    ]

    if _LOG_LLM_IO and not _LOG_LLM_IO_FULL:
        _log_prompt_summary(prompt_messages, *_log_targets)
    elif _LOG_LLM_IO_FULL:
        for i, msg in enumerate(prompt_messages):
            role = getattr(msg, "type", type(msg).__name__)
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            for _l in _log_targets:
                _l.info("📨 [LLM Input] msg[%d] role=%s:\n%s", i, role, content)

    response = await llm_with_tools.ainvoke(prompt_messages)

    if _LOG_LLM_IO and not _LOG_LLM_IO_FULL:
        _log_response_summary(response, *_log_targets)
        # Log tool calls if present
        if getattr(response, "tool_calls", None):
            for tc in response.tool_calls:
                for _l in _log_targets:
                    _l.info("🔧 [LLM Output] tool_call: %s args=%s", tc.get("name"), tc.get("args"))
    elif _LOG_LLM_IO_FULL:
        # Log text content
        resp_text = response.content if isinstance(response.content, str) else str(response.content)
        for _l in _log_targets:
            _l.info("📩 [LLM Output] content:\n%s", resp_text)
        # Log tool calls if present
        if getattr(response, "tool_calls", None):
            for tc in response.tool_calls:
                for _l in _log_targets:
                    _l.info("🔧 [LLM Output] tool_call: %s args=%s", tc.get("name"), tc.get("args"))
        # Log reasoning / thinking content if present (native reasoning models)
        thinking = None
        if hasattr(response, "additional_kwargs"):
            thinking = response.additional_kwargs.get("reasoning") or response.additional_kwargs.get("thinking")
        if thinking:
            for _l in _log_targets:
                _l.info("🧠 [LLM Reasoning]:\n%s", thinking)

    if hasattr(response, "usage_metadata") and response.usage_metadata:
        in_tok = response.usage_metadata.get("input_tokens", 0)
        total_tok = response.usage_metadata.get("total_tokens", 0)
        logger.info("📊 [Context Monitor] input=%d total=%d", in_tok, total_tok)
        if slog:
            slog.info("📊 [Context Monitor] input=%d total=%d", in_tok, total_tok)
        if total_tok > 100_000:
            logger.warning("🚨 [Context Monitor] Approaching context limit (total=%d)", total_tok)
            if slog:
                slog.warning("🚨 [Context Monitor] Approaching context limit (total=%d)", total_tok)

    result: dict[str, object] = {
        "messages": await sanitize_messages_for_state([*drained_messages, response], source="chem_agent"),
    }
    if drained_artifacts:
        result["artifacts"] = drained_artifacts
    if drained_workspace_events:
        result["workspace_events"] = drained_workspace_events
        result["workspace_projection"] = drained_workspace_projection
    if remaining_pending_tasks or state.get("pending_worker_tasks"):
        result["pending_worker_tasks"] = remaining_pending_tasks
    return result


def route_from_agent(state: ChemState) -> str:
    last_message = state["messages"][-1]
    return "tools_executor" if getattr(last_message, "tool_calls", None) else "__end__"


# ---------------------------------------------------------------------------
# Phase 4: Meta-Cognitive Reflection — Memory Consolidation Node
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402
import os as _os
from typing import Any as _Any

from langchain_core.messages import HumanMessage as _HumanMessage
from pydantic import BaseModel as _BaseModel
from pydantic import Field as _Field

_CONCLUSIVE_STATUSES = frozenset({"rejected", "lead", "exploring"})
_MAX_CONSOLIDATION_PAYLOAD_CHARS = 6_000

_CONSOLIDATION_SYSTEM_PROMPT = """\
你是一位资深计算化学审阅员。你的唯一任务是从当前分子实验结果中提炼出高度浓缩的科学知识，追加到项目黑板。

规则：
- 不要重复黑板已有的条目。
- 每条规律或教训必须极度简练（一句话，<=20 字中文），直接说结论。
- 例如："卤代衍生物 logP 普遍超标" 或 "吲哚核心改善了不含氯取代基的结合亲和力"。
- 如果没有新发现，返回空列表即可。
"""


class KnowledgeExtraction(_BaseModel):
    new_rules: list[str] = _Field(
        default_factory=list,
        description="New design rules from lead molecules. Single sentence each. Omit duplicates.",
    )
    new_failed_attempts: list[str] = _Field(
        default_factory=list,
        description="Failure lessons from rejected molecules. Single sentence each. Omit duplicates.",
    )
    updated_goal: str | None = _Field(
        default=None,
        description="Updated research goal only if intent clearly shifted. None = unchanged.",
    )


async def memory_consolidation_node(
    state: ChemState, config: RunnableConfig = None  # type: ignore[assignment]
) -> dict[str, _Any]:
    """Phase 4 reflection node: scan molecule_tree, distil discoveries into scratchpad.

    Returns an empty dict (no-op) when there is nothing new to learn, so it
    never delays low-value turns.
    """
    tree: dict = state.get("molecule_tree") or {}
    current_scratchpad: dict = dict(state.get("scratchpad") or {})

    # 1. Only reflect when some molecules have definitive outcomes.
    conclusive_nodes = {
        aid: node
        for aid, node in tree.items()
        if isinstance(node, dict) and node.get("status") in _CONCLUSIVE_STATUSES
    }
    if not conclusive_nodes:
        logger.debug("[consolidation] No conclusive nodes — skipping.")
        return {}

    # 2. Build payload (capped to control token spend).
    human_content = (
        f"【现有黑板内容】：\n{_json.dumps(current_scratchpad, ensure_ascii=False, indent=2)}\n\n"
        f"【当前有结论的分子诊断结果】：\n{_json.dumps(conclusive_nodes, ensure_ascii=False, indent=2)}"
    )
    if len(human_content) > _MAX_CONSOLIDATION_PAYLOAD_CHARS:
        human_content = human_content[:_MAX_CONSOLIDATION_PAYLOAD_CHARS] + "\n…[内容已截断]"

    # 3. Structured-output call. CHEMAGENT_CONSOLIDATION_MODEL allows routing to a
    #    lighter/cheaper model (e.g., gpt-4o-mini) independently of the main agent.
    model = _os.environ.get("CHEMAGENT_CONSOLIDATION_MODEL") or state.get("selected_model")
    llm = build_llm(structured_schema=KnowledgeExtraction, model=model)

    try:
        extraction: KnowledgeExtraction = await llm.ainvoke([
            SystemMessage(content=_CONSOLIDATION_SYSTEM_PROMPT),
            _HumanMessage(content=human_content),
        ])
    except Exception:  # noqa: BLE001
        logger.warning("[consolidation] LLM call failed — scratchpad unchanged.", exc_info=True)
        return {}

    # 4. Skip state write when nothing new was extracted.
    if not extraction.new_rules and not extraction.new_failed_attempts and not extraction.updated_goal:
        logger.debug("[consolidation] Nothing new extracted.")
        return {}

    # 5. Append-only merge into scratchpad.
    updated: dict = dict(current_scratchpad)
    if extraction.updated_goal:
        updated["research_goal"] = extraction.updated_goal
    if extraction.new_rules:
        updated["established_rules"] = list(updated.get("established_rules") or []) + extraction.new_rules
    if extraction.new_failed_attempts:
        updated["failed_attempts"] = list(updated.get("failed_attempts") or []) + extraction.new_failed_attempts

    logger.info(
        "[consolidation] +%d rules  +%d failures  goal_changed=%s",
        len(extraction.new_rules),
        len(extraction.new_failed_attempts),
        bool(extraction.updated_goal),
    )
    return {"scratchpad": updated}
"""Sub-Agent Graph Factory
===========================

Builds isolated LangGraph ``StateGraph`` instances for sub-agent execution.
Each sub-graph runs under a unique ``thread_id`` while sharing the parent's
``AsyncSqliteSaver`` — achieving logical isolation with physical persistence
(which is required for HITL interrupt/resume to survive HTTP request cycles).

Graph topology
--------------
- ``plan`` mode (no tools):
      sub_agent → END
- ``explore`` / ``general`` / ``custom`` (with tools):
      sub_agent ↔ sub_tools_executor  (ReAct loop)

Both nodes are produced by factory helpers that return closures capturing the
mode-specific tool set and HITL bypass flag.
"""

from __future__ import annotations

import json
import logging
from hashlib import sha256
from typing import Any, cast

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.execution_context import build_execution_stop_intercept, has_unfinished_tasks
from app.agents.middleware.postprocessors import TOOL_POSTPROCESSORS
from app.agents.sub_agents.runtime_tools import INTERNAL_SUB_AGENT_TOOLS
from app.agents.state import ChemState, MoleculeWorkspaceEntry
from app.agents.sub_agents.prompts import SubAgentMode, get_sub_agent_prompt
from app.agents.utils import (
    apply_active_smiles_update,
    build_llm,
    normalize_messages_for_api,
    parse_tool_output,
    sanitize_messages_for_state,
    tool_result_to_text,
    update_molecule_workspace,
)

logger = logging.getLogger(__name__)

_SUB_RECURSION_LIMIT = 25
_TERMINAL_TOOL_NAMES = {
    "tool_task_complete",
    "tool_exit_plan_mode",
    "tool_task_stop",
    "tool_report_failure",
}


def _normalize_tool_signature(tool_name: str, args: Any) -> str:
    try:
        normalized_args = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        normalized_args = repr(args)
    return sha256(f"{tool_name}|{normalized_args}".encode("utf-8")).hexdigest()


def _classify_failure(error_text: str, category_hint: str | None = None) -> tuple[str, bool]:
    if category_hint:
        lowered_hint = category_hint.strip().lower()
        if lowered_hint in {"infrastructure", "timeout"}:
            return lowered_hint, True
        if lowered_hint:
            return lowered_hint, False

    lowered = str(error_text or "").lower()
    if any(token in lowered for token in ("timeout", "timed out", "429", "rate limit", "connection", "peer closed", "chunked read")):
        if "timeout" in lowered or "timed out" in lowered:
            return "timeout", True
        return "infrastructure", True
    if any(token in lowered for token in ("schema", "validation", "invalid", "missing required", "field required")):
        return "validation", False
    if any(token in lowered for token in ("not available", "unsupported", "not found")):
        return "unsupported_tool", False
    if any(token in lowered for token in ("forbidden", "denied", "policy", "not allowed")):
        return "policy", False
    return "unknown", False


def _next_failure_state(
    control: dict[str, Any],
    *,
    tool_name: str,
    args: Any,
    error_text: str,
    category_hint: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    signature = _normalize_tool_signature(tool_name, args)
    previous_signature = str(control.get("last_failure_signature") or "")
    streak = int(control.get("failure_streak") or 0)
    streak = streak + 1 if previous_signature == signature else 1
    failure_category, is_recoverable = _classify_failure(error_text, category_hint)
    updated = {
        **control,
        "last_failure_signature": signature,
        "last_failure_tool": tool_name,
        "last_failure_error": error_text,
        "last_failure_category": failure_category,
        "failure_streak": streak,
    }
    if streak < 3:
        return updated, None
    return updated, {
        "status": "failed",
        "summary": f"子智能体在工具 {tool_name} 上连续失败 {streak} 次，已触发熔断。",
        "error": error_text,
        "failure_category": failure_category,
        "failed_tool_name": tool_name,
        "failed_args_signature": signature,
        "is_recoverable": is_recoverable,
        "recommended_action": "spawn",
    }


def _reset_failure_state(control: dict[str, Any]) -> dict[str, Any]:
    return {
        **control,
        "last_failure_signature": "",
        "last_failure_tool": "",
        "last_failure_error": "",
        "last_failure_category": "",
        "failure_streak": 0,
    }


def _route_after_sub_tools_executor(state: ChemState) -> str:
    payload = state.get("sub_agent_result")
    if isinstance(payload, dict):
        status = str(payload.get("status") or "").strip().lower()
        if status in {"completed", "plan_pending_approval", "failed", "stopped"}:
            return "__end__"
    return "sub_agent"


def extract_sub_agent_outcome(result: dict[str, Any] | None) -> tuple[str, list[dict], str | None, dict[str, Any] | None]:
    """Extract final text, produced artifacts, advisory active SMILES, and terminal payload."""
    payload = result or {}
    messages = payload.get("messages", []) if isinstance(payload, dict) else []
    artifacts = payload.get("artifacts", []) if isinstance(payload, dict) else []
    active_smiles = payload.get("active_smiles") if isinstance(payload, dict) else None
    sub_agent_result = payload.get("sub_agent_result") if isinstance(payload, dict) else None
    final_text = "子智能体已完成任务，但未产生文本输出。"

    if isinstance(sub_agent_result, dict):
        structured_summary = str(sub_agent_result.get("summary") or "").strip()
        if structured_summary:
            final_text = structured_summary

    if final_text == "子智能体已完成任务，但未产生文本输出。":
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                content = msg.content
                final_text = content if isinstance(content, str) else str(content)
                break

    return (
        final_text,
        artifacts if isinstance(artifacts, list) else [],
        active_smiles if isinstance(active_smiles, str) else None,
        sub_agent_result if isinstance(sub_agent_result, dict) else None,
    )


# ── Node factory: LLM reasoning step ─────────────────────────────────────────


def _make_sub_agent_node(
    mode: SubAgentMode,
    tools: list,
    custom_instructions: str,
    skill_markdown: str,
    skill_listing: str = "",
) -> Any:
    """Return an async LangGraph-compatible node function for the LLM step."""

    system_prompt = get_sub_agent_prompt(mode, custom_instructions, skill_markdown, skill_listing)

    async def sub_agent_node(state: ChemState, config: RunnableConfig) -> dict:  # noqa: ARG001
        llm = build_llm(model=state.get("selected_model"))
        llm_bound = llm.bind_tools(tools) if tools else llm

        safe_messages = normalize_messages_for_api(state["messages"])

        prompt_messages = [SystemMessage(content=system_prompt), *safe_messages]
        response = await llm_bound.ainvoke(prompt_messages, config=config)

        control = dict(state.get("subtask_control") or {})
        if (
            control.get("strict_execution")
            and not getattr(response, "tool_calls", None)
            and has_unfinished_tasks(state.get("tasks") or [])
        ):
            response = await llm_bound.ainvoke(
                [*prompt_messages, SystemMessage(content=build_execution_stop_intercept())],
                config=config,
            )
        return {"messages": await sanitize_messages_for_state([response], source=f"sub_agent.{mode.value}")}

    # Give the closure a stable name for LangGraph event tracing.
    sub_agent_node.__name__ = f"sub_agent[{mode.value}]"
    sub_agent_node.__qualname__ = sub_agent_node.__name__
    return sub_agent_node


# ── Node factory: tool execution step ────────────────────────────────────────


def _make_sub_tools_executor(
    tool_lookup: dict[str, Any],
    bypass_hitl: bool,
) -> Any:
    """Return an async LangGraph-compatible node function for the tools step.

    Parameters
    ----------
    tool_lookup:
        Mapping of ``tool_name -> BaseTool`` for only the permitted tools.
    bypass_hitl:
        When ``True`` the heavy-tool approval gate is skipped entirely
        (``explore`` / ``plan`` modes guarantee zero interrupts).
        When ``False`` (``general`` / ``custom``) the gate delegates to the
        shared ``HEAVY_TOOLS`` frozenset from the root executor.
    """
    # Lazy import to break circular dependency:
    # sub_graph → nodes/executor → nodes/__init__ → nodes/agent → lg_tools → sub_graph
    from app.agents.nodes.executor import HEAVY_TOOLS as _ROOT_HEAVY_TOOLS  # noqa: PLC0415
    effective_heavy_tools: frozenset[str] = frozenset() if bypass_hitl else _ROOT_HEAVY_TOOLS

    async def sub_tools_executor_node(state: ChemState, config: RunnableConfig) -> dict:
        last_message = state["messages"][-1]
        new_active_smiles = state.get("active_smiles")
        sub_agent_result = state.get("sub_agent_result") if isinstance(state.get("sub_agent_result"), dict) else None
        subtask_control = dict(state.get("subtask_control") or {})
        molecule_workspace: list[MoleculeWorkspaceEntry] = [
            cast(MoleculeWorkspaceEntry, dict(entry))
            for entry in state.get("molecule_workspace", [])
            if isinstance(entry, dict)
        ]
        artifacts: list[dict] = []
        tool_messages: list[ToolMessage] = []
        tool_calls = list(getattr(last_message, "tool_calls", []))

        # ── Heavy-tool approval gate (mirrors root executor) ──────────────────
        heavy_call = next(
            (tc for tc in tool_calls if tc["name"] in effective_heavy_tools), None
        )
        if heavy_call is not None:
            resume_value = interrupt({
                "type": "approval_required",
                "tool_call_id": heavy_call["id"],
                "tool_name": heavy_call["name"],
                "args": heavy_call.get("args", {}),
            })
            action = (
                (resume_value or {}).get("action", "approve")
                if isinstance(resume_value, dict) else "approve"
            )
            if action == "reject":
                return {
                    "messages": await sanitize_messages_for_state([
                        ToolMessage(
                            content=json.dumps(
                                {"status": "rejected", "message": "User rejected this tool."},
                                ensure_ascii=False,
                            ),
                            tool_call_id=heavy_call["id"],
                            name=heavy_call["name"],
                        )
                    ], source="sub_tools_executor.rejected"),
                    "active_smiles": new_active_smiles,
                    "artifacts": [],
                }
            elif action == "modify":
                patched_args = (resume_value or {}).get("args", heavy_call.get("args", {}))
                for tc in tool_calls:
                    if tc["id"] == heavy_call["id"]:
                        tc["args"] = patched_args
                        break
            # action == "approve" → fall through

        # ── Execute each tool call ─────────────────────────────────────────────
        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            tool_call_id = tool_call.get("id", "")
            args = tool_call.get("args", {})
            tool = tool_lookup.get(tool_name)

            if tool is None:
                error_text = f"Tool '{tool_name}' is not available in this sub-agent mode."
                tool_messages.append(
                    ToolMessage(
                        content=json.dumps(
                            {"error": error_text},
                            ensure_ascii=False,
                        ),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                )
                subtask_control, forced_failure = _next_failure_state(
                    subtask_control,
                    tool_name=tool_name,
                    args=args,
                    error_text=error_text,
                    category_hint="unsupported_tool",
                )
                if forced_failure is not None:
                    sub_agent_result = forced_failure
                    tool_messages.append(
                        ToolMessage(
                            content=tool_result_to_text(forced_failure),
                            tool_call_id=tool_call_id,
                            name="tool_report_failure",
                        )
                    )
                    break
                continue

            try:
                raw_output = await tool.ainvoke(args, config=config)
                parsed = parse_tool_output(raw_output)

                if parsed is not None:
                    if tool_name in _TERMINAL_TOOL_NAMES:
                        sub_agent_result = parsed
                        logger.debug(
                            "[PROTOCOL] terminal payload received: tool=%s summary=%r",
                            tool_name,
                            str(parsed.get("summary") or "")[:120],
                        )
                    else:
                        new_active_smiles = apply_active_smiles_update(
                            tool_name, parsed, new_active_smiles
                        )
                        molecule_workspace = update_molecule_workspace(molecule_workspace, tool_name, parsed, args)
                        postprocessor = TOOL_POSTPROCESSORS.get(tool_name)
                        if postprocessor is not None:
                            parsed = await postprocessor(parsed, args, artifacts, config)

                forced_failure: dict[str, Any] | None = None
                parsed_status = str((parsed or {}).get("status") or "").strip().lower()
                if parsed_status in {"error", "failed", "timeout", "rejected"}:
                    error_text = str((parsed or {}).get("error") or (parsed or {}).get("message") or raw_output)
                    subtask_control, forced_failure = _next_failure_state(
                        subtask_control,
                        tool_name=tool_name,
                        args=args,
                        error_text=error_text,
                        category_hint=str((parsed or {}).get("failure_category") or "").strip() or None,
                    )
                elif tool_name not in _TERMINAL_TOOL_NAMES:
                    subtask_control = _reset_failure_state(subtask_control)

                content = tool_result_to_text(parsed) if parsed is not None else str(raw_output)
                tool_messages.append(
                    ToolMessage(content=content, tool_call_id=tool_call_id, name=tool_name)
                )

                if forced_failure is not None:
                    sub_agent_result = forced_failure
                    tool_messages.append(
                        ToolMessage(
                            content=tool_result_to_text(forced_failure),
                            tool_call_id=tool_call_id,
                            name="tool_report_failure",
                        )
                    )
                    break

                if tool_name in _TERMINAL_TOOL_NAMES:
                    break

            except Exception as exc:
                error_text = str(exc)
                tool_messages.append(
                    ToolMessage(
                        content=json.dumps({"error": error_text}, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                )
                subtask_control, forced_failure = _next_failure_state(
                    subtask_control,
                    tool_name=tool_name,
                    args=args,
                    error_text=error_text,
                )
                if forced_failure is not None:
                    sub_agent_result = forced_failure
                    tool_messages.append(
                        ToolMessage(
                            content=tool_result_to_text(forced_failure),
                            tool_call_id=tool_call_id,
                            name="tool_report_failure",
                        )
                    )
                    break

        return {
            "messages": await sanitize_messages_for_state(tool_messages, source="sub_tools_executor"),
            "active_smiles": new_active_smiles,
            "artifacts": artifacts,
            "molecule_workspace": molecule_workspace,
            "sub_agent_result": sub_agent_result,
            "subtask_control": subtask_control,
        }

    sub_tools_executor_node.__name__ = "sub_tools_executor"
    sub_tools_executor_node.__qualname__ = "sub_tools_executor"
    return sub_tools_executor_node


# ── Routing ───────────────────────────────────────────────────────────────────


def _route_from_sub_agent(state: ChemState) -> str:
    last = state["messages"][-1]
    return "sub_tools_executor" if getattr(last, "tool_calls", None) else "__end__"


# ── Public graph builder ───────────────────────────────────────────────────────


def build_sub_agent_graph(
    mode: SubAgentMode,
    tools: list,
    checkpointer: Any,
    custom_instructions: str = "",
    skill_markdown: str = "",
    skill_listing: str = "",
) -> Any:
    """Compile an isolated sub-agent ``StateGraph``.

    Parameters
    ----------
    mode:
        Operating mode; determines which tools are available and what persona
        the LLM will adopt.
    tools:
        Pre-filtered tool list (output of ``get_tools_for_mode()``).  Must
        already have ``ALWAYS_DENIED`` entries removed.
    checkpointer:
        **Required** — must be the shared ``AsyncSqliteSaver`` from the
        parent runtime.  In-memory checkpointers are not accepted because they
        cannot survive the HTTP request cycle boundary that separates an
        ``interrupt()`` from its subsequent ``resume``.
    custom_instructions:
        Only used for ``SubAgentMode.custom``; injected verbatim into the
        persona prompt.
    skill_markdown:
        Only used for ``SubAgentMode.custom``; local markdown skills injected
        alongside custom instructions.
    skill_listing:
        Compact ``<available_skills>`` XML block injected into the system
        prompt for all non-custom modes.  Sub-agents can call
        ``tool_load_skill`` to fetch full skill content on demand.

    Returns
    -------
    CompiledGraph
        A compiled ``StateGraph[ChemState]`` ready for ``ainvoke()`` / ``astream()``.
    """
    if checkpointer is None:
        raise ValueError(
            "build_sub_agent_graph() requires a persistent checkpointer. "
            "Pass the shared AsyncSqliteSaver from runtime.get_checkpointer(). "
            "In-memory checkpointers are rejected to protect HITL resume semantics."
        )

    bypass_hitl = mode in (SubAgentMode.explore, SubAgentMode.plan)
    runtime_tools = [*tools, *INTERNAL_SUB_AGENT_TOOLS]
    tool_lookup: dict[str, Any] = {t.name: t for t in runtime_tools}

    graph: StateGraph = StateGraph(ChemState)

    sub_agent_fn = _make_sub_agent_node(mode, runtime_tools, custom_instructions, skill_markdown, skill_listing)
    graph.add_node("sub_agent", sub_agent_fn)

    if runtime_tools:
        sub_executor_fn = _make_sub_tools_executor(tool_lookup, bypass_hitl)
        graph.add_node("sub_tools_executor", sub_executor_fn)

        graph.add_edge(START, "sub_agent")
        graph.add_conditional_edges(
            "sub_agent",
            _route_from_sub_agent,
            {"sub_tools_executor": "sub_tools_executor", "__end__": END},
        )
        graph.add_conditional_edges(
            "sub_tools_executor",
            _route_after_sub_tools_executor,
            {"sub_agent": "sub_agent", "__end__": END},
        )
    else:
        graph.add_edge(START, "sub_agent")
        graph.add_edge("sub_agent", END)

    return graph.compile(checkpointer=checkpointer)

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
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.postprocessors import TOOL_POSTPROCESSORS
from app.agents.state import ChemState
from app.agents.sub_agent_prompts import SubAgentMode, get_sub_agent_prompt
from app.agents.utils import (
    apply_active_smiles_update,
    build_llm,
    normalize_messages_for_api,
    parse_tool_output,
    tool_result_to_text,
)

logger = logging.getLogger(__name__)

_SUB_RECURSION_LIMIT = 25


# ── Node factory: LLM reasoning step ─────────────────────────────────────────


def _make_sub_agent_node(
    mode: SubAgentMode,
    tools: list,
    custom_instructions: str,
) -> Any:
    """Return an async LangGraph-compatible node function for the LLM step."""

    system_prompt = get_sub_agent_prompt(mode, custom_instructions)

    async def sub_agent_node(state: ChemState, config: RunnableConfig) -> dict:  # noqa: ARG001
        llm = build_llm()
        llm_bound = llm.bind_tools(tools) if tools else llm

        safe_messages = normalize_messages_for_api(state["messages"])

        response = await llm_bound.ainvoke(
            [SystemMessage(content=system_prompt), *safe_messages],
            config=config,
        )
        return {"messages": [response]}

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
                    "messages": [
                        ToolMessage(
                            content=json.dumps(
                                {"status": "rejected", "message": "User rejected this tool."},
                                ensure_ascii=False,
                            ),
                            tool_call_id=heavy_call["id"],
                            name=heavy_call["name"],
                        )
                    ],
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
                tool_messages.append(
                    ToolMessage(
                        content=json.dumps(
                            {"error": f"Tool '{tool_name}' is not available in this sub-agent mode."},
                            ensure_ascii=False,
                        ),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                )
                continue

            try:
                raw_output = await tool.ainvoke(args, config=config)
                parsed = parse_tool_output(raw_output)

                if parsed is not None:
                    new_active_smiles = apply_active_smiles_update(
                        tool_name, parsed, new_active_smiles
                    )
                    postprocessor = TOOL_POSTPROCESSORS.get(tool_name)
                    if postprocessor is not None:
                        parsed = await postprocessor(parsed, args, artifacts, config)

                content = tool_result_to_text(parsed) if parsed is not None else str(raw_output)
                tool_messages.append(
                    ToolMessage(content=content, tool_call_id=tool_call_id, name=tool_name)
                )

            except Exception as exc:
                tool_messages.append(
                    ToolMessage(
                        content=json.dumps({"error": str(exc)}, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                )

        return {
            "messages": tool_messages,
            "active_smiles": new_active_smiles,
            "artifacts": artifacts,
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
    tool_lookup: dict[str, Any] = {t.name: t for t in tools}

    graph: StateGraph = StateGraph(ChemState)

    sub_agent_fn = _make_sub_agent_node(mode, tools, custom_instructions)
    graph.add_node("sub_agent", sub_agent_fn)

    if tools:
        sub_executor_fn = _make_sub_tools_executor(tool_lookup, bypass_hitl)
        graph.add_node("sub_tools_executor", sub_executor_fn)

        graph.add_edge(START, "sub_agent")
        graph.add_conditional_edges(
            "sub_agent",
            _route_from_sub_agent,
            {"sub_tools_executor": "sub_tools_executor", "__end__": END},
        )
        graph.add_edge("sub_tools_executor", "sub_agent")
    else:
        # plan mode — single node, no tools
        graph.add_edge(START, "sub_agent")
        graph.add_edge("sub_agent", END)

    return graph.compile(checkpointer=checkpointer)

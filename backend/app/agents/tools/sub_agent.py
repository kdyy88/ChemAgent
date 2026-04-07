"""run_sub_agent — Root-Agent Tool for Sub-Agent Delegation
===========================================================

Implements the ``tool_run_sub_agent`` LangChain tool that the root agent uses
to delegate a focused sub-task to an isolated LangGraph sub-graph.

Architecture
------------
Execution model:
  - The tool is called by ``tools_executor_node`` exactly like any other tool.
  - Internally it compiles a fresh ``StateGraph`` for the requested mode,
    sharing the parent's ``AsyncSqliteSaver`` checkpointer.
  - The sub-graph runs under a **deterministic** ``sub_thread_id`` derived from
    the parent thread and the task description.  Determinism is essential for
    HITL resume: the same inputs will find the same checkpoint on re-invocation.

HITL / interrupt propagation:
  - ``explore`` / ``plan`` modes set ``bypass_hitl=True`` → guaranteed zero
    interrupts, so ``ainvoke()`` always returns a terminal state.
  - ``general`` / ``custom`` modes can trigger HEAVY_TOOLS approval gates
    inside the sub-graph.  When ``ainvoke()`` returns with ``"__interrupt__"``
    in the result dict, the tool calls LangGraph's ``interrupt()`` to bubble
    the approval request up to the **parent** graph.  The parent checkpoints
    (SQLite) and surfaces the interrupt to the frontend.
  - On user approval, the parent engine resumes via ``Command(resume=...)``.
    The root ``tools_executor_node`` re-invokes this tool with identical args.
    The deterministic ``sub_thread_id`` finds the persisted sub-graph checkpoint.
    The tool calls ``interrupt()`` again — this time LangGraph's scratchpad
    returns the resume value instead of raising.  That value is forwarded to
    the sub-graph as ``Command(resume=resume_value)``.

Free streaming:
  - The parent ``engine.py`` calls ``graph.astream_events(version="v2")``.
  - This call sets up a ``CallbackManager`` in a contextvar.
  - ``langgraph.config.get_config()`` (called inside the tool) retrieves that
    config, including the active callbacks.
  - Those callbacks are forwarded verbatim to ``sub_graph.ainvoke(config=...)``.
  - LangGraph's ``CallbackManager`` tree then automatically propagates every
    ``on_chat_model_stream`` event from the sub-graph up through the parent's
    event stream.  The frontend sees sub-agent tokens with no additional code.

Timeout:
  - Each sub-graph invocation is bounded by ``_SUB_AGENT_TIMEOUT`` seconds
    (default 120 s) via ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agents.sub_graph import build_sub_agent_graph
from app.agents.tool_registry import SubAgentMode, get_tools_for_mode

logger = logging.getLogger(__name__)

_INTERRUPT_KEY = "__interrupt__"
_MAX_CONTEXT_CHARS = 8_000
_SUB_AGENT_TIMEOUT = 120.0


# ── Helpers ───────────────────────────────────────────────────────────────────


def _truncate_context(context: str) -> str:
    """Hard-cap context at ``_MAX_CONTEXT_CHARS`` with a visible snip marker."""
    if len(context) <= _MAX_CONTEXT_CHARS:
        return context
    half = _MAX_CONTEXT_CHARS // 2
    snipped = len(context) - _MAX_CONTEXT_CHARS
    return (
        context[:half]
        + f"\n…[上下文已截断，略去 {snipped} 字符]…\n"
        + context[-half:]
    )


def _deterministic_sub_thread_id(parent_thread_id: str, mode: str, task: str) -> str:
    """Hash (parent_thread, mode, task) → stable 16-hex sub_thread_id.

    Determinism ensures that re-invocation after parent HITL resume finds the
    **same** sub-graph checkpoint (same sub_thread_id → same SQLite row).
    """
    key = f"{parent_thread_id}|{mode}|{task}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"sub_{digest}"


def _extract_final_response(messages: list) -> str:
    """Return the last AI text message that has no pending tool_calls."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = msg.content
            return content if isinstance(content, str) else str(content)
    return "子智能体已完成任务，但未产生文本输出。"


# ── Args schema ───────────────────────────────────────────────────────────────


class RunSubAgentArgs(BaseModel):
    mode: str = Field(
        description=(
            "子智能体工作模式：\n"
            "- explore: 只读信息调研（分子性质、PubChem、联网搜索），保证不产生副作用\n"
            "- plan:    纯 LLM 推理，生成结构化 Markdown 计划，无工具调用\n"
            "- general: 完整生化计算执行（全量 RDKit + Open Babel 工具）\n"
            "- custom:  使用 custom_tools 白名单和 custom_instructions 自定义指令"
        )
    )
    task: str = Field(
        description="分配给子智能体的明确任务描述。应包含具体目标、分子信息、预期输出格式。",
        min_length=5,
        max_length=1_000,
    )
    context: str = Field(
        default="",
        description=(
            "传递给子智能体的背景信息（当前 SMILES、已知实验数据、前置步骤结果等）。"
            "子智能体无法访问当前对话历史——所有必要信息必须在此传入。上限 8000 字符。"
        ),
        max_length=10_000,
    )
    custom_instructions: str = Field(
        default="",
        description="仅 mode=custom 有效：自定义系统指令，完全替换默认 Persona。",
        max_length=2_000,
    )
    custom_tools: list[str] = Field(
        default_factory=list,
        description=(
            "仅 mode=custom 有效：工具名称白名单（如 ['tool_validate_smiles', 'tool_pubchem_lookup']）。"
            "non existent 或被永久禁用的工具会报错。"
        ),
    )


# ── Tool implementation ────────────────────────────────────────────────────────


@tool(args_schema=RunSubAgentArgs)
async def tool_run_sub_agent(
    mode: str,
    task: str,
    context: str = "",
    custom_instructions: str = "",
    custom_tools: list[str] | None = None,
) -> str:
    """委派一个明确的子任务给隔离的专项子智能体执行。

    子智能体运行在独立的 LangGraph 线程中，拥有专属工具集和 Persona System Prompt。
    子智能体的 Token 流式输出会实时透传到当前对话气泡中（免费流式传输）。

    **适用场景**
    - mode="explore"：深度只读调研（分子 Lipinski、PubChem 数据、机制文献），无副作用
    - mode="plan"：将复杂实验任务分解为步骤清单（纯 LLM，无工具调用）
    - mode="general"：独立执行多步化学计算（如：净化 → 3D 构象 → PDBQT 全流程）
    - mode="custom"：使用自定义工具集和指令集的专项子智能体

    **约束**
    1. 不要将单工具调用委派给子智能体——直接调用那个工具更高效
    2. 子智能体不能访问当前对话历史，必须在 context 中传入所有必要信息
    3. 子智能体不能再委派子任务（depth=1 强制限制）
    """
    # ── Retrieve parent context via LangGraph config ──────────────────────────
    try:
        from langgraph.config import get_config as _lg_get_config  # noqa: PLC0415
        lg_config = _lg_get_config()
    except Exception:
        lg_config = {}

    configurable = lg_config.get("configurable") or {}
    parent_thread_id: str = configurable.get("thread_id", "default")
    callbacks = lg_config.get("callbacks")

    # ── Resolve mode and filtered tool set ───────────────────────────────────
    try:
        sub_agent_mode = SubAgentMode(mode)
    except ValueError:
        return json.dumps(
            {"status": "error", "error": f"Unknown sub-agent mode: '{mode}'"},
            ensure_ascii=False,
        )

    try:
        filtered_tools = get_tools_for_mode(sub_agent_mode, custom_tools or None)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    # ── Shared checkpointer (MUST be the SQLite instance) ─────────────────────
    try:
        from app.agents.runtime import get_checkpointer  # noqa: PLC0415
        checkpointer = get_checkpointer()
    except RuntimeError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    # ── Build sub-graph ───────────────────────────────────────────────────────
    sub_graph = build_sub_agent_graph(
        sub_agent_mode,
        filtered_tools,
        checkpointer,
        custom_instructions=custom_instructions or "",
    )

    # ── Deterministic thread isolation ────────────────────────────────────────
    sub_thread_id = _deterministic_sub_thread_id(parent_thread_id, mode, task)

    # Forward parent callbacks for free streaming (LangGraph propagates
    # on_chat_model_stream events from the sub-graph up through astream_events).
    sub_config: dict = {
        "configurable": {"thread_id": sub_thread_id},
        "recursion_limit": 25,
    }
    if callbacks is not None:
        sub_config["callbacks"] = callbacks

    # ── HITL resume detection ─────────────────────────────────────────────────
    # Check whether the sub-graph already has a persisted checkpoint with a
    # pending interrupt.  This is the "second invocation" branch triggered when
    # the parent resumes after the user clicked Approve / Reject / Modify.
    sub_snapshot = await sub_graph.aget_state(
        {"configurable": {"thread_id": sub_thread_id}}
    )
    has_pending_interrupt = bool(sub_snapshot and sub_snapshot.interrupts)

    if has_pending_interrupt:
        # Re-surface the sub-graph's interrupt payload to get the parent's
        # resume decision.  On this (second) invocation, LangGraph's scratchpad
        # returns the resume value instead of raising GraphInterrupt.
        pending = sub_snapshot.interrupts[0]
        pending_payload = pending.value if isinstance(pending.value, dict) else {}
        resume_value = interrupt(
            {
                "type": "sub_agent_approval",
                "sub_thread_id": sub_thread_id,
                **pending_payload,
            }
        )
        # resume_value = {"action": "approve" | "reject" | "modify", "args": {...}}
        sub_input: dict | Command = Command(resume=resume_value)
        logger.info(
            "Sub-agent resuming: sub_thread_id=%s action=%s",
            sub_thread_id,
            (resume_value or {}).get("action"),
        )
    else:
        # Fresh run — build initial state for the sub-graph.
        safe_context = _truncate_context(context or "")
        task_msg = task
        if safe_context:
            task_msg = f"{task}\n\n---\n上下文:\n{safe_context}"
        sub_input = {
            "messages": [HumanMessage(content=task_msg)],
            "active_smiles": None,
            "artifacts": [],
            "tasks": [],
            "is_complex": False,
        }
        logger.info(
            "Sub-agent starting: mode=%s sub_thread_id=%s task=%.80s",
            mode,
            sub_thread_id,
            task,
        )

    # ── Execute sub-graph ─────────────────────────────────────────────────────
    try:
        result = await asyncio.wait_for(
            sub_graph.ainvoke(sub_input, config=sub_config),  # type: ignore[arg-type]
            timeout=_SUB_AGENT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return json.dumps(
            {
                "status": "timeout",
                "error": f"子智能体超时（>{_SUB_AGENT_TIMEOUT:.0f}s），任务未完成。",
                "mode": mode,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("Sub-agent execution error: sub_thread_id=%s", sub_thread_id)
        return json.dumps({"status": "error", "error": str(exc), "mode": mode}, ensure_ascii=False)

    # ── HITL bubble-up (general/custom only; explore/plan bypass_hitl=True) ──
    # If the sub-graph was interrupted by a HEAVY_TOOLS approval gate, delegate
    # the decision to the parent by calling interrupt() here.
    # On the FIRST call: LangGraph raises GraphInterrupt → parent pauses.
    # On RESUME call   : this branch is not reached (has_pending_interrupt=True
    #                    above handles the re-invocation instead).
    if isinstance(result, dict):
        sub_interrupts = result.get(_INTERRUPT_KEY)
        if sub_interrupts:
            pending_int = sub_interrupts[0]
            pending_payload = pending_int.value if isinstance(pending_int.value, dict) else {}
            logger.info(
                "Sub-agent interrupted: sub_thread_id=%s payload=%s",
                sub_thread_id,
                pending_payload,
            )
            # This call raises GraphInterrupt on first encounter (parent pauses).
            interrupt(
                {
                    "type": "sub_agent_approval",
                    "sub_thread_id": sub_thread_id,
                    **pending_payload,
                }
            )
            # Unreachable — interrupt() raises. Needed only for static analysis.
            return ""  # type: ignore[return-value]

    # ── Extract and return final response ─────────────────────────────────────
    messages = result.get("messages", []) if isinstance(result, dict) else []
    final_response = _extract_final_response(messages)

    logger.info(
        "Sub-agent complete: sub_thread_id=%s response_len=%d",
        sub_thread_id,
        len(final_response),
    )

    return json.dumps(
        {
            "status": "ok",
            "mode": mode,
            "sub_thread_id": sub_thread_id,
            "response": final_response,
        },
        ensure_ascii=False,
    )

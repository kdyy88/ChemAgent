"""
Session management — DefaultPattern multi-agent team per conversation.

Each ``ChatSession`` holds the team created by ``create_chem_team()``:
  • ``user_proxy``   — outer-chat initiator (no LLM, not in DefaultPattern group)
  • ``pattern``      — DefaultPattern (holds agents + context_variables)
  • ``ctx``          — shared ContextVariables (routing state, plan text)
  • ``prior_messages`` — full message history saved between phases

HITL phases (unchanged external contract)
──────────────────────────────────────────
  ``run_planning(prompt)``   → Phase 1: planner proposes plan and calls
                               ``submit_plan_for_approval(plan_details)``
                               which fires ``TerminateTarget()`` to stop the group.
  ``run_execution(approval)``→ Phase 2: planner dispatches specialists via
                               ``set_routing_target(target)`` tools; ends with
                               ``finish_workflow(final_summary)`` → ``TerminateTarget()``.
  ``generate_greeting()``    → One-shot welcome (fresh history, 5 rounds).

Both phases use ``a_run_group_chat(pattern, messages, max_rounds)``.
Prior messages from one phase are saved and prepended to the next so the
group sees full context across phases.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from autogen import ConversableAgent
from autogen.agentchat import a_run_group_chat
from autogen.agentchat.group import ContextVariables
from autogen.agentchat.group.patterns import DefaultPattern

from app.agents import create_chem_team
from app.agents.config import build_llm_config, get_fast_llm_config, get_resolved_model_name


# ── Session ───────────────────────────────────────────────────────────────────

SESSION_TTL_SECONDS = 60 * 15


@dataclass
class ChatSession:
    session_id: str
    user_proxy: ConversableAgent
    pattern: DefaultPattern

    # Shared ContextVariables — state + routing target live here
    ctx: ContextVariables = field(default_factory=ContextVariables)

    # Full message history — saved after each phase, prepended to next phase
    prior_messages: list = field(default_factory=list)

    # HITL state: "idle" | "awaiting_approval" | "executing"
    state: str = "idle"

    # When True, skip the approval gate — go straight to execution after planning
    auto_approve: bool = False

    # Tracks how many planning turns have occurred
    turn_count: int = 0

    # Model names bound to each agent (sent to frontend in session.started)
    agent_models: dict[str, str] = field(default_factory=dict)

    # ── Snapshot fields for reconnect state replay ────────────────────────
    last_plan: str | None = None
    last_todo: str | None = None
    last_answer: str | None = None
    last_turn_id: str | None = None
    last_run_id: str | None = None

    last_accessed_at: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        self.last_accessed_at = time.time()

    # ── Phase 1: Planning ─────────────────────────────────────────────────

    async def run_planning(self, prompt: str):
        """Planner analyses the prompt and calls ``submit_plan_for_approval``.

        ``submit_plan_for_approval`` returns ``ReplyResult(target=TerminateTarget())``
        which stops the DefaultPattern GroupChat cleanly.  ``ctx["state"]`` is
        set to ``"awaiting_approval"`` by the tool.

        Message history from previous turns (``self.prior_messages``) is
        prepended so the group has full context across multi-turn sessions.

        Returns an ``AsyncRunResponseProtocol`` whose ``.events`` yields all
        events from all agents in the group.
        """
        self.touch()
        self.turn_count += 1
        self.last_answer = None

        today = date.today().isoformat()
        new_msg = {"role": "user", "content": f"今日日期：{today}\n\n{prompt}"}

        if self.prior_messages:
            messages = list(self.prior_messages) + [new_msg]
        else:
            messages = new_msg["content"]

        return await a_run_group_chat(self.pattern, messages, max_rounds=60)

    # ── Phase 2: Execution ────────────────────────────────────────────────

    async def run_execution(self, user_input: str):
        """Resume after approval — planner dispatches specialists via tool calls.

        The approval message includes a ``[SYSTEM]`` directive so the planner
        immediately generates the ``<todo>`` checklist and calls
        ``set_routing_target`` to dispatch the first step.

        ``prior_messages`` (populated from Phase 1 drain) gives the group full
        context of the planning phase.  Execution ends when the planner calls
        ``finish_workflow(final_summary)`` → ``TerminateTarget()``.
        """
        self.state = "executing"
        # Clear last_plan so the RunCompletionEvent fallback in events.py
        # does not re-emit plan.status:awaiting_approval after finish_workflow
        # sets state back to "idle" with last_plan still populated.
        self.last_plan = None

        approval_msg = (
            f"{user_input}\n\n"
            "[SYSTEM]: 计划已获批准。请 **立刻** 生成 <todo> 检查清单，"
            "然后调用 set_routing_target 工具派发第一步。"
        )

        messages = list(self.prior_messages) + [
            {"role": "user", "content": approval_msg}
        ]

        return await a_run_group_chat(self.pattern, messages, max_rounds=60)

    # generate_greeting() removed — static greeting is now sent directly
    # from chat.py/_send_static_greeting() without any LLM calls.


# ── Session manager ───────────────────────────────────────────────────────────


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._lock = asyncio.Lock()

    def _prune(self) -> None:
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.last_accessed_at > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            self._sessions.pop(sid, None)

    async def create(self, agent_models: dict[str, str] | None = None) -> ChatSession:
        async with self._lock:
            self._prune()
            session_id = f"sess_{uuid4().hex}"
            models = agent_models or {}
            model_name = models.get("manager") or models.get("chem_brain") or models.get("planner")

            llm_config = build_llm_config(model_name)
            user_proxy, pattern, ctx, resolved_models = create_chem_team(
                llm_config=llm_config
            )

            session = ChatSession(
                session_id=session_id,
                user_proxy=user_proxy,
                pattern=pattern,
                ctx=ctx,
                agent_models=resolved_models,
            )
            self._sessions[session_id] = session
            return session

    async def get_or_create(
        self,
        session_id: str | None,
        agent_models: dict[str, str] | None = None,
    ) -> tuple[ChatSession, bool]:
        async with self._lock:
            self._prune()
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                session.touch()
                return session, False

        session = await self.create(agent_models=agent_models)
        return session, True

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def active_count(self) -> int:
        async with self._lock:
            self._prune()
            return len(self._sessions)


session_manager = SessionManager()

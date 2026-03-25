"""
Session management — ChemBrain + Executor pair per conversation.

Each ``ChatSession`` holds a single (brain, executor) agent pair created via
``create_agent_pair()``.

Async-first architecture: all run methods use AG2's ``a_run()`` which returns
``AsyncRunResponseProtocol`` with non-blocking ``async for`` event iteration
on the same event loop.  No threading primitives — uses ``asyncio.Lock``.

HITL phases:
- ``run_planning(prompt)``     → Phase 1: brain outputs ``<plan>`` + ``[AWAITING_APPROVAL]``
- ``run_execution(approval)``  → Phase 2: brain executes ``<todo>`` with tool calls
- ``generate_greeting()``      → One-shot welcome message
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from autogen import ConversableAgent

from app.agents import create_agent_pair
from app.agents.config import build_llm_config, get_fast_llm_config, get_resolved_model_name


# ── Session ───────────────────────────────────────────────────────────────────

SESSION_TTL_SECONDS = 60 * 15


@dataclass
class ChatSession:
    session_id: str
    brain: ConversableAgent
    executor: ConversableAgent

    # HITL state: "idle" | "awaiting_approval" | "executing"
    state: str = "idle"

    # When True, skip the approval gate — go straight to execution after planning
    auto_approve: bool = False

    # Tracks how many planning turns have occurred (for context-window safety)
    turn_count: int = 0

    # Model name actually bound to the brain (sent to frontend in session.started)
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
        """Brain analyses prompt → outputs ``<plan>`` + ``[AWAITING_APPROVAL]``.

        Uses ``clear_history=False`` so the brain retains conversation context
        across turns (enabling continuous dialogue).  The greeting's own
        ``clear_history=True`` ensures the very first exchange starts clean.

        After ``turn_count > 2`` the summary method switches from
        ``"last_msg"`` to ``"reflection_with_llm"`` to compress context and
        prevent token-window explosion on long sessions.

        Returns an ``AsyncRunResponseProtocol`` whose ``.events`` is an
        ``AsyncIterable[BaseEvent]`` — iterate with ``async for``.
        """
        self.touch()
        self.state = "awaiting_approval"
        self.turn_count += 1

        # Reset per-turn snapshot accumulators
        self.last_answer = None

        today = date.today().isoformat()
        full_prompt = f"今日日期：{today}\n\n{prompt}"

        # Use reflection_with_llm after turn 2 to summarize growing context
        if self.turn_count > 2:
            summary_method = "reflection_with_llm"
            summary_args = {
                "summary_prompt": (
                    "Summarize the conversation so far concisely, focusing on "
                    "the user's chemical research goals and key results. "
                    "Keep under 200 words."
                ),
                "llm_config": get_fast_llm_config(),
            }
        else:
            summary_method = "last_msg"
            summary_args = {}

        return await self.executor.a_run(
            recipient=self.brain,
            message=full_prompt,
            max_turns=4,
            summary_method=summary_method,
            summary_args=summary_args,
            clear_history=False,
        )

    # ── Phase 2: Execution ────────────────────────────────────────────────

    async def run_execution(self, user_input: str):
        """Resume after approval — brain generates ``<todo>`` and calls tools.

        Injects a ``[SYSTEM]`` override to ensure the brain immediately starts
        executing rather than wasting a turn on pleasantries.

        Uses ``clear_history=False`` so the brain can see its own ``<plan>``.
        """
        self.state = "executing"

        approval_msg = (
            f"{user_input}\n\n"
            "[SYSTEM]: The plan has been approved. "
            "Generate the <todo> checklist now and execute the FIRST tool call immediately."
        )

        return await self.executor.a_run(
            recipient=self.brain,
            message=approval_msg,
            clear_history=False,
            max_turns=30,
            summary_method="last_msg",
        )

    # ── Greeting ──────────────────────────────────────────────────────────

    async def generate_greeting(self):
        """One-shot greeting from ChemBrain for new sessions.

        Also serves as connection pre-warming (first LLM TCP handshake).
        """
        return await self.executor.a_run(
            recipient=self.brain,
            message=(
                "请用中文简短友好地问候用户，介绍你是专业化学助手 ChemAgent，"
                "简述你能帮助用户做什么（如查询化合物信息、绘制分子结构图、"
                "分析分子性质、搜索文献等），并邀请用户提问。"
                "语气自然亲切，不超过3句话。纯文本，不要使用 Markdown。"
                "回复末尾输出 [TERMINATE]"
            ),
            max_turns=1,
            clear_history=True,
            summary_method="last_msg",
        )


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
            model_name = models.get("manager") or models.get("chem_brain")

            llm_config = build_llm_config(model_name)
            brain, executor = create_agent_pair(llm_config=llm_config)

            resolved = get_resolved_model_name(model_name)
            resolved_models = {"chem_brain": resolved}

            session = ChatSession(
                session_id=session_id,
                brain=brain,
                executor=executor,
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

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4

from autogen.io.run_response import RunResponseProtocol

from app.agents.manager import (
    create_manager,
    create_routing_agent,
    parse_routing_decision,
)
from app.agents.factory import create_executor_agent
from app.agents.specialists.researcher import create_researcher
from app.agents.specialists.visualizer import create_visualizer
from app.api.runtime import (
    AgentTeam,
    MultiAgentRunPlan,
    SpecialistSummary,
    build_synthesis_prompt,
    format_turn_history,
)


SESSION_TTL_SECONDS = 60 * 30


# ── Session ───────────────────────────────────────────────────────────────────


@dataclass
class ChatSession:
    session_id: str
    team: AgentTeam
    has_history: bool = False
    # Compact per-turn record for cross-turn context injection into the Router.
    # Each entry: {"user": <original prompt>, "result": <specialist findings>}
    # _do_routing uses only the last 3 entries to avoid prompt bloat.
    turn_history: list = field(default_factory=list)
    last_accessed_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def touch(self) -> None:
        self.last_accessed_at = time.time()

    def _do_routing(self, prompt: str) -> dict:
        """Phase 1: run the pre-initialised Router synchronously.

        Injects up to the last 3 turns of history so the Router can resolve
        ambiguous references (e.g. "相关分子" → specific compound names).
        Uses clear_history=True so previous routing exchanges don't leak in.
        """
        context_prefix = format_turn_history(self.turn_history)
        routing_prompt = (
            f"{context_prefix}\n\n当前用户问题：{prompt}"
            if context_prefix
            else f"当前用户问题：{prompt}"
        )

        result = self.team.router_trigger.initiate_chat(
            self.team.router,
            message=routing_prompt,
            summary_method="last_msg",
            clear_history=True,
            silent=True,
        )
        routing_text = result.summary or ""
        return parse_routing_decision(routing_text)

    def run_turn(self, prompt: str) -> MultiAgentRunPlan:
        """Build and return a MultiAgentRunPlan.

        Phase 1 (routing) is executed synchronously here — one fast-model LLM call.
        Phase 2 RunResponseProtocol objects are set up lazily; actual LLM calls fire
        during event iteration in the daemon thread inside _stream_run_events.
        Phase 3 synthesis is encapsulated as a factory closure.

        Call via asyncio.to_thread from the async event loop to avoid blocking it.
        """
        self.touch()

        # ── Phase 1: Route ────────────────────────────────────────────────────
        routing = self._do_routing(prompt)
        route = routing["route"]
        refined = routing.get("refined_prompts") or {}
        rationale = routing.get("routing_rationale") or ""
        # Reserve a slot in turn_history now; filled after Phase 2 in synthesis_factory
        turn_idx = len(self.turn_history)
        self.turn_history.append({"user": prompt, "result": ""})
        # ── Phase 2: Set up specialist runs (lazy) ────────────────────────────
        is_general = route == ["general"]
        phase2_items: list[tuple[str, RunResponseProtocol]] = []

        if not is_general:
            if "researcher" in route:
                res_prompt = refined.get("researcher") or prompt
                res_resp = self.team.researcher_executor.run(
                    recipient=self.team.researcher,
                    message=res_prompt,
                    clear_history=True,
                    summary_method="last_msg",
                    silent=False,
                )
                phase2_items.append(("Researcher", res_resp))

            if "visualizer" in route:
                vis_prompt = refined.get("visualizer") or prompt
                vis_resp = self.team.visualizer_executor.run(
                    recipient=self.team.visualizer,
                    message=vis_prompt,
                    clear_history=True,
                    summary_method="last_msg",
                    silent=False,
                )
                phase2_items.append(("Visualizer", vis_resp))

        # ── Phase 3 factory: called after Phase 2 events are exhausted ────────
        had_history = self.has_history  # capture value BEFORE setting True
        self.has_history = True

        def synthesis_factory(
            summaries: list[SpecialistSummary],
        ):
            # Persist what this turn found so future turns can resolve references
            result_parts = [s.summary for s in summaries if s.success and s.summary]
            self.turn_history[turn_idx]["result"] = "; ".join(result_parts) or "无结果"

            synthesis_prompt = build_synthesis_prompt(
                original_prompt=prompt,
                routing_rationale=rationale,
                summaries=summaries,
                is_general=is_general,
            )
            manager_trigger = create_executor_agent(
                name="Manager_Trigger",
                max_consecutive_auto_reply=0,
                is_termination_msg=lambda _: True,
            )
            return manager_trigger.run(
                recipient=self.team.manager,
                message=synthesis_prompt,
                clear_history=not had_history,  # Manager keeps multi-turn context
                summary_method="last_msg",
                silent=False,
            )

        return MultiAgentRunPlan(
            routing_rationale=rationale,
            phase2_items=phase2_items,
            synthesis_factory=synthesis_factory,
        )


# ── Session manager ───────────────────────────────────────────────────────────


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()

    def _prune(self) -> None:
        now = time.time()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if now - session.last_accessed_at > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            self._sessions.pop(sid, None)

    def create(self) -> ChatSession:
        with self._lock:
            self._prune()
            session_id = f"sess_{uuid4().hex}"

            manager = create_manager()
            router, router_trigger = create_routing_agent()
            visualizer, visualizer_executor = create_visualizer()
            researcher, researcher_executor = create_researcher()

            team = AgentTeam(
                manager=manager,
                router=router,
                router_trigger=router_trigger,
                visualizer=visualizer,
                visualizer_executor=visualizer_executor,
                researcher=researcher,
                researcher_executor=researcher_executor,
            )
            session = ChatSession(session_id=session_id, team=team)
            self._sessions[session_id] = session
            return session

    def get_or_create(self, session_id: str | None) -> tuple[ChatSession, bool]:
        with self._lock:
            self._prune()
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                session.touch()
                return session, False

        session = self.create()
        return session, True

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


session_manager = SessionManager()

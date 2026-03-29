"""
Unit tests for events.py — the AG2 event → WebSocket frame bridge.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.api.events import _event_to_frames, _make_frame


# ── _make_frame ───────────────────────────────────────────────────────────────


class TestMakeFrame:
    def test_basic_structure(self):
        frame = _make_frame("run.started", {"key": "val"}, "sess-1", "turn-1", "run-1")
        assert frame["type"] == "run.started"
        assert frame["session_id"] == "sess-1"
        assert frame["turn_id"] == "turn-1"
        assert frame["run_id"] == "run-1"
        assert frame["key"] == "val"


# ── _event_to_frames — TextEvent ─────────────────────────────────────────────


class TestTextEventFrames:
    def _make_text_event(self, content: str, sender: str = "planner"):
        event = MagicMock()
        event.__class__.__name__ = "TextEvent"
        # Patch isinstance checks
        from autogen.events.agent_events import TextEvent

        event.__class__ = TextEvent
        event.content = MagicMock()
        event.content.content = content
        event.content.sender = sender
        return event

    def _make_executed_function_event(
        self,
        func_name: str,
        call_id: str = "call-001",
        content: str = "{}",
        is_exec_success: bool = True,
    ):
        """Build a mock ExecutedFunctionEvent for control tool tests."""
        from autogen.events.agent_events import ExecutedFunctionEvent

        event = MagicMock()
        event.__class__ = ExecutedFunctionEvent
        event.content = MagicMock()
        event.content.func_name = func_name
        event.content.call_id = call_id
        event.content.content = content
        event.content.is_exec_success = is_exec_success
        event.content.arguments = {}
        return event

    def _make_session(self, state: str = "idle"):
        session = MagicMock()
        session.state = state
        session.last_todo = None
        return session

    def test_plan_proposed_emitted(self):
        event = self._make_text_event("<plan>Step 1: Do X\nStep 2: Do Y</plan>")
        session = self._make_session()
        frames = _event_to_frames(
            event=event,
            session_id="s",
            turn_id="t",
            run_id="r",
            pending_calls={},
            session=session,
            phase_state={},
        )
        plan_frames = [f for f in frames if f["type"] == "plan.proposed"]
        assert len(plan_frames) == 1
        assert "Step 1" in plan_frames[0]["plan"]

    def test_submit_plan_for_approval_tool_emits_plan_status(self):
        """ExecutedFunctionEvent for submit_plan_for_approval → plan.status frame
        and session.state = 'awaiting_approval'."""
        event = self._make_executed_function_event("submit_plan_for_approval")
        session = self._make_session()
        frames = _event_to_frames(
            event=event,
            session_id="s",
            turn_id="t",
            run_id="r",
            pending_calls={"call-001": {"tool": "submit_plan_for_approval", "arguments": {}}},
            session=session,
            phase_state={},
        )
        status_frames = [f for f in frames if f["type"] == "plan.status"]
        assert len(status_frames) == 1
        assert status_frames[0]["status"] == "awaiting_approval"
        assert session.state == "awaiting_approval"

    def test_finish_workflow_tool_resets_state(self):
        """ExecutedFunctionEvent for finish_workflow → session.state = 'idle'."""
        event = self._make_executed_function_event("finish_workflow")
        session = self._make_session(state="executing")
        _event_to_frames(
            event=event,
            session_id="s",
            turn_id="t",
            run_id="r",
            pending_calls={"call-001": {"tool": "finish_workflow", "arguments": {}}},
            session=session,
            phase_state={},
        )
        assert session.state == "idle"

    def test_planner_text_without_plan_emits_assistant_message(self):
        """Plain planner narration (no <plan>, no sentinels) emits assistant.message."""
        event = self._make_text_event("I will now dispatch the data specialist.")
        session = self._make_session()
        frames = _event_to_frames(
            event=event,
            session_id="s",
            turn_id="t",
            run_id="r",
            pending_calls={},
            session=session,
            phase_state={},
        )
        text_frames = [f for f in frames if f["type"] == "assistant.message"]
        assert len(text_frames) == 1
        assert "dispatch the data specialist" in text_frames[0]["message"]

    def test_planner_final_answer_emits_assistant_message(self):
        """
        A plain final-answer message (no plan/todo markers)
        should emit assistant.message cleanly.
        """
        event = self._make_text_event("Final answer here.")
        session = self._make_session()
        frames = _event_to_frames(
            event=event,
            session_id="s",
            turn_id="t",
            run_id="r",
            pending_calls={},
            session=session,
            phase_state={},
        )
        text_frames = [f for f in frames if f["type"] == "assistant.message"]
        assert len(text_frames) == 1
        assert "Final answer here." in text_frames[0]["message"]

    def test_non_agent_sender_ignored(self):
        """Messages from non-specialist senders (tool_executor, user_proxy, etc.) are suppressed."""
        event = self._make_text_event("Some text", sender="tool_executor")
        session = self._make_session()
        frames = _event_to_frames(
            event=event,
            session_id="s",
            turn_id="t",
            run_id="r",
            pending_calls={},
            session=session,
            phase_state={},
        )
        assert frames == []

    def test_todo_during_execution_shows_narration(self):
        """
        Execution-step announcements contain <todo> and narration like
        "正在执行第2步…".  The <todo> block gets a dedicated todo.progress frame,
        and the narration text (stripped of <todo> tags) also appears in
        assistant.message so the user sees live progress in the answer bubble.
        """
        content = "<todo>\n- [x] Step 1 ✓\n- [ ] Step 2\n</todo>\n\n正在执行第2步…"
        event = self._make_text_event(content)
        session = self._make_session(state="executing")
        frames = _event_to_frames(
            event=event,
            session_id="s",
            turn_id="t",
            run_id="r",
            pending_calls={},
            session=session,
            phase_state={},
        )
        # todo.progress frame must be emitted
        todo_frames = [f for f in frames if f["type"] == "todo.progress"]
        assert len(todo_frames) == 1

        # assistant.message is also emitted with <todo> stripped, showing narration
        text_frames = [f for f in frames if f["type"] == "assistant.message"]
        assert len(text_frames) == 1
        assert "<todo>" not in text_frames[0]["message"]
        assert "正在执行第2步" in text_frames[0]["message"]

    def test_todo_in_final_answer_passes_through(self):
        """
        The final answer TextEvent may contain a <todo> block (all items
        checked) followed by the actual report text.
        assistant.message should be emitted with the <todo> block stripped
        but the report text preserved.
        """
        content = "<todo>\n- [x] Step 1 ✓\n- [x] Step 2 ✓\n</todo>\n\n分析完成，报告如下：azithromycin…"
        event = self._make_text_event(content)
        session = self._make_session(state="executing")
        frames = _event_to_frames(
            event=event,
            session_id="s",
            turn_id="t",
            run_id="r",
            pending_calls={},
            session=session,
            phase_state={},
        )
        text_frames = [f for f in frames if f["type"] == "assistant.message"]
        assert len(text_frames) == 1
        msg = text_frames[0]["message"]
        assert "分析完成" in msg
        assert "<todo>" not in msg

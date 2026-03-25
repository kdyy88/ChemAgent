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
    def _make_text_event(self, content: str, sender: str = "chem_brain"):
        event = MagicMock()
        event.__class__.__name__ = "TextEvent"
        # Patch isinstance checks
        from autogen.events.agent_events import TextEvent

        event.__class__ = TextEvent
        event.content = MagicMock()
        event.content.content = content
        event.content.sender = sender
        return event

    def _make_session(self, state: str = "idle"):
        session = MagicMock()
        session.state = state
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

    def test_awaiting_approval_sentinel(self):
        event = self._make_text_event("Here is the plan [AWAITING_APPROVAL]")
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
        status_frames = [f for f in frames if f["type"] == "plan.status"]
        assert len(status_frames) == 1
        assert status_frames[0]["status"] == "awaiting_approval"
        assert session.state == "awaiting_approval"

    def test_terminate_resets_state(self):
        event = self._make_text_event("Done [TERMINATE]")
        session = self._make_session(state="executing")
        _event_to_frames(
            event=event,
            session_id="s",
            turn_id="t",
            run_id="r",
            pending_calls={},
            session=session,
            phase_state={},
        )
        assert session.state == "idle"

    def test_awaiting_approval_suppresses_message(self):
        """
        Messages that contain [AWAITING_APPROVAL] are pipeline narration
        (e.g. "以上是我为您制定的计划 [AWAITING_APPROVAL]").  They should
        NOT emit an assistant.message frame — the plan.status frame already
        carries the structured information.
        """
        event = self._make_text_event("Hello [AWAITING_APPROVAL] world [TERMINATE]")
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
        assert len(text_frames) == 0

    def test_terminate_sentinel_stripped_from_final_answer(self):
        """
        A plain final-answer message (no plan/todo/AWAITING_APPROVAL markers)
        should still emit assistant.message with [TERMINATE] stripped out.
        """
        event = self._make_text_event("Final answer here. [TERMINATE]")
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
        assert "[TERMINATE]" not in text_frames[0]["message"]
        assert "Final answer here." in text_frames[0]["message"]

    def test_non_brain_sender_ignored(self):
        event = self._make_text_event("Some text", sender="executor")
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

    def test_todo_during_execution_suppresses_message(self):
        """
        Execution-step announcements contain <todo> and narration like
        "正在执行第1步…".  The assistant.message must be suppressed because
        the todo block already has a dedicated todo.progress frame.
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
        text_frames = [f for f in frames if f["type"] == "assistant.message"]
        assert len(text_frames) == 0
        # But todo.progress should still be emitted
        todo_frames = [f for f in frames if f["type"] == "todo.progress"]
        assert len(todo_frames) == 1

    def test_todo_in_final_answer_passes_through(self):
        """
        The final answer TextEvent may contain a <todo> block (all items
        checked) followed by the actual report text and [TERMINATE].
        assistant.message should be emitted with the <todo> block stripped
        but the report text preserved.
        """
        content = "<todo>\n- [x] Step 1 ✓\n- [x] Step 2 ✓\n</todo>\n\n分析完成，报告如下：azithromycin… [TERMINATE]"
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
        # After processing [TERMINATE], session.state → "idle", so message passes
        text_frames = [f for f in frames if f["type"] == "assistant.message"]
        assert len(text_frames) == 1
        msg = text_frames[0]["message"]
        assert "分析完成" in msg
        assert "<todo>" not in msg
        assert "[TERMINATE]" not in msg

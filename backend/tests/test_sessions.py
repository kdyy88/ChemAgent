"""
Unit tests for sessions.py — async session management.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.sessions import ChatSession, SessionManager


# ── ChatSession ───────────────────────────────────────────────────────────────


class TestChatSession:
    def test_initial_state_is_idle(self, mock_session):
        assert mock_session.state == "idle"

    def test_auto_approve_defaults_false(self, mock_session):
        assert mock_session.auto_approve is False

    def test_turn_count_starts_at_zero(self, mock_session):
        assert mock_session.turn_count == 0

    def test_lock_is_asyncio_lock(self, mock_session):
        assert isinstance(mock_session.lock, asyncio.Lock)

    def test_touch_updates_last_accessed(self, mock_session):
        before = mock_session.last_accessed_at
        mock_session.touch()
        assert mock_session.last_accessed_at >= before


# ── SessionManager ────────────────────────────────────────────────────────────


class TestSessionManager:
    @pytest.mark.asyncio
    @patch("app.api.sessions.create_chem_team")
    @patch("app.api.sessions.build_llm_config")
    async def test_create_returns_new_session(self, mock_llm, mock_team):
        mock_llm.return_value = MagicMock()
        mock_team.return_value = (MagicMock(), MagicMock(), MagicMock(), {"planner": "test-model"})

        manager = SessionManager()
        session = await manager.create()

        assert session.session_id.startswith("sess_")
        assert session.state == "idle"

    @pytest.mark.asyncio
    @patch("app.api.sessions.create_chem_team")
    @patch("app.api.sessions.build_llm_config")
    async def test_get_or_create_returns_existing(self, mock_llm, mock_team):
        mock_llm.return_value = MagicMock()
        mock_team.return_value = (MagicMock(), MagicMock(), MagicMock(), {"planner": "test-model"})

        manager = SessionManager()
        first = await manager.create()
        result, created = await manager.get_or_create(first.session_id)

        assert result.session_id == first.session_id
        assert created is False

    @pytest.mark.asyncio
    @patch("app.api.sessions.create_chem_team")
    @patch("app.api.sessions.build_llm_config")
    async def test_get_or_create_creates_new_for_unknown_id(self, mock_llm, mock_team):
        mock_llm.return_value = MagicMock()
        mock_team.return_value = (MagicMock(), MagicMock(), MagicMock(), {"planner": "test-model"})

        manager = SessionManager()
        result, created = await manager.get_or_create("nonexistent-id")

        assert created is True
        assert result.session_id.startswith("sess_")

    @pytest.mark.asyncio
    @patch("app.api.sessions.create_chem_team")
    @patch("app.api.sessions.build_llm_config")
    async def test_clear_removes_session(self, mock_llm, mock_team):
        mock_llm.return_value = MagicMock()
        mock_team.return_value = (MagicMock(), MagicMock(), MagicMock(), {"planner": "test-model"})

        manager = SessionManager()
        session = await manager.create()
        await manager.clear(session.session_id)
        count = await manager.active_count()
        assert count == 0

    @pytest.mark.asyncio
    @patch("app.api.sessions.create_chem_team")
    @patch("app.api.sessions.build_llm_config")
    async def test_active_count(self, mock_llm, mock_team):
        mock_llm.return_value = MagicMock()
        mock_team.return_value = (MagicMock(), MagicMock(), MagicMock(), {"planner": "test-model"})

        manager = SessionManager()
        await manager.create()
        await manager.create()
        count = await manager.active_count()
        assert count == 2


# ── Continuous conversation (a_run_group_chat calls) ──────────────────────────


class TestContinuousConversation:
    """Verify that session phases call a_run_group_chat with correct arguments."""

    @pytest.mark.asyncio
    @patch("app.api.sessions.a_run_group_chat", new_callable=AsyncMock)
    async def test_run_planning_passes_string_without_prior_messages(
        self, mock_run, mock_session
    ):
        """run_planning() with no prior history should pass a plain string message."""
        mock_run.return_value = MagicMock()
        assert mock_session.prior_messages == []

        await mock_session.run_planning("What is aspirin?")

        assert mock_run.called
        _pattern, messages, *_ = mock_run.call_args.args
        assert isinstance(messages, str), (
            "No prior_messages → messages should be a plain string"
        )
        assert "What is aspirin?" in messages

    @pytest.mark.asyncio
    @patch("app.api.sessions.a_run_group_chat", new_callable=AsyncMock)
    async def test_run_planning_increments_turn_count(self, mock_run, mock_session):
        """Each run_planning call should increment turn_count."""
        mock_run.return_value = MagicMock()

        assert mock_session.turn_count == 0
        await mock_session.run_planning("First question")
        assert mock_session.turn_count == 1
        await mock_session.run_planning("Follow-up question")
        assert mock_session.turn_count == 2

    @pytest.mark.asyncio
    @patch("app.api.sessions.a_run_group_chat", new_callable=AsyncMock)
    async def test_run_planning_with_prior_messages_passes_list(
        self, mock_run, mock_session
    ):
        """run_planning() with prior_messages should prepend history as a list."""
        mock_run.return_value = MagicMock()
        mock_session.prior_messages = [{"role": "assistant", "content": "Hello"}]

        await mock_session.run_planning("Second turn")

        _pattern, messages, *_ = mock_run.call_args.args
        assert isinstance(messages, list), (
            "With prior_messages → messages should be a list"
        )
        assert messages[0] == {"role": "assistant", "content": "Hello"}

    @pytest.mark.asyncio
    @patch("app.api.sessions.a_run_group_chat", new_callable=AsyncMock)
    async def test_run_execution_passes_list_messages(self, mock_run, mock_session):
        """run_execution() should always pass a list (approval + prior_messages)."""
        mock_run.return_value = MagicMock()

        await mock_session.run_execution("Approved")

        assert mock_run.called
        _pattern, messages, *_ = mock_run.call_args.args
        assert isinstance(messages, list), (
            "run_execution must pass a list including the approval message"
        )
        assert any("Approved" in m.get("content", "") for m in messages), (
            "Approval text should appear in the messages list"
        )

    @pytest.mark.asyncio
    @patch("app.api.sessions.a_run_group_chat", new_callable=AsyncMock)
    async def test_run_execution_sets_state_executing(self, mock_run, mock_session):
        """run_execution() must set state='executing' before calling a_run_group_chat."""
        captured_state: list[str] = []

        async def _capture_state(*args, **kwargs):
            captured_state.append(mock_session.state)
            return MagicMock()

        mock_run.side_effect = _capture_state
        await mock_session.run_execution("Approved")
        assert captured_state == ["executing"]

    def test_greeting_is_now_static(self, mock_session):
        """generate_greeting() has been removed — greeting is a static string
        sent directly by chat.py/_send_static_greeting() with zero LLM calls.
        Verify that ChatSession no longer has a generate_greeting method.
        """
        assert not hasattr(mock_session, "generate_greeting"), (
            "ChatSession.generate_greeting() should not exist — "
            "static greeting is handled in chat.py without LLM calls"
        )

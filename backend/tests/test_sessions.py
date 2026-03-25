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
    @patch("app.api.sessions.create_agent_pair")
    @patch("app.api.sessions.build_llm_config")
    async def test_create_returns_new_session(self, mock_llm, mock_pair):
        mock_llm.return_value = MagicMock()
        mock_pair.return_value = (MagicMock(), MagicMock())

        manager = SessionManager()
        session = await manager.create()

        assert session.session_id.startswith("sess_")
        assert session.state == "idle"

    @pytest.mark.asyncio
    @patch("app.api.sessions.create_agent_pair")
    @patch("app.api.sessions.build_llm_config")
    async def test_get_or_create_returns_existing(self, mock_llm, mock_pair):
        mock_llm.return_value = MagicMock()
        mock_pair.return_value = (MagicMock(), MagicMock())

        manager = SessionManager()
        first = await manager.create()
        result, created = await manager.get_or_create(first.session_id)

        assert result.session_id == first.session_id
        assert created is False

    @pytest.mark.asyncio
    @patch("app.api.sessions.create_agent_pair")
    @patch("app.api.sessions.build_llm_config")
    async def test_get_or_create_creates_new_for_unknown_id(self, mock_llm, mock_pair):
        mock_llm.return_value = MagicMock()
        mock_pair.return_value = (MagicMock(), MagicMock())

        manager = SessionManager()
        result, created = await manager.get_or_create("nonexistent-id")

        assert created is True
        assert result.session_id.startswith("sess_")

    @pytest.mark.asyncio
    @patch("app.api.sessions.create_agent_pair")
    @patch("app.api.sessions.build_llm_config")
    async def test_clear_removes_session(self, mock_llm, mock_pair):
        mock_llm.return_value = MagicMock()
        mock_pair.return_value = (MagicMock(), MagicMock())

        manager = SessionManager()
        session = await manager.create()
        await manager.clear(session.session_id)
        count = await manager.active_count()
        assert count == 0

    @pytest.mark.asyncio
    @patch("app.api.sessions.create_agent_pair")
    @patch("app.api.sessions.build_llm_config")
    async def test_active_count(self, mock_llm, mock_pair):
        mock_llm.return_value = MagicMock()
        mock_pair.return_value = (MagicMock(), MagicMock())

        manager = SessionManager()
        await manager.create()
        await manager.create()
        count = await manager.active_count()
        assert count == 2


# ── Continuous conversation (history retention) ───────────────────────────────


class TestContinuousConversation:
    """Verify that run_planning preserves history across turns."""

    @pytest.mark.asyncio
    async def test_run_planning_uses_clear_history_false(self, mock_session):
        """run_planning() must pass clear_history=False to a_run()
        so the brain retains prior conversation context."""
        await mock_session.run_planning("What is aspirin?")

        call_kwargs = mock_session.executor.a_run.call_args
        assert call_kwargs.kwargs.get("clear_history") is False or (
            len(call_kwargs.args) > 4 and call_kwargs.args[4] is False
        ), "run_planning must use clear_history=False"

    @pytest.mark.asyncio
    async def test_run_planning_increments_turn_count(self, mock_session):
        """Each run_planning call should increment turn_count."""
        assert mock_session.turn_count == 0
        await mock_session.run_planning("First question")
        assert mock_session.turn_count == 1
        await mock_session.run_planning("Follow-up question")
        assert mock_session.turn_count == 2

    @pytest.mark.asyncio
    async def test_run_execution_uses_clear_history_false(self, mock_session):
        """run_execution() must also preserve history (clear_history=False)."""
        # First do a planning run to set state
        await mock_session.run_planning("Plan something")
        mock_session.executor.a_run.reset_mock()

        # Provide fresh async response mock
        async def _empty():
            return
            yield

        fresh_response = MagicMock()
        fresh_response.events = _empty()
        mock_session.executor.a_run = AsyncMock(return_value=fresh_response)

        await mock_session.run_execution("Approved")

        call_kwargs = mock_session.executor.a_run.call_args
        assert call_kwargs.kwargs.get("clear_history") is False

    @pytest.mark.asyncio
    async def test_greeting_uses_clear_history_true(self, mock_session):
        """generate_greeting() should use clear_history=True
        since it's the very first exchange."""
        await mock_session.generate_greeting()

        call_kwargs = mock_session.executor.a_run.call_args
        assert call_kwargs.kwargs.get("clear_history") is True

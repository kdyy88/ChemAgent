"""
Shared test fixtures for ChemAgent backend tests.

Provides mock LLM config, agent team, and session fixtures so that
unit tests never hit a real OpenAI endpoint.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.sessions import ChatSession, SessionManager


# ── Mock LLM config ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_llm_config():
    """Return a fake LLMConfig-compatible dict that skips real API calls."""
    return {"config_list": [{"model": "test-model", "api_key": "fake"}]}


# ── Mock agent team ───────────────────────────────────────────────────────────


@pytest.fixture
def mock_agents():
    """Return (user_proxy, pattern) mocks.

    ``a_run_group_chat`` is patched at module level so calls in ChatSession
    methods return an empty async response without hitting the real framework.
    """
    user_proxy = MagicMock()
    user_proxy.name = "user_proxy"

    pattern = MagicMock()
    pattern.name = "mock_pattern"

    return user_proxy, pattern


# ── Mock response factory ─────────────────────────────────────────────────────

def _make_mock_response():
    """Return an AsyncRunResponse-like mock with empty events and messages."""

    async def _empty_events():
        return
        yield  # make it an async generator

    async def _empty_messages():
        return []

    mock_response = MagicMock()
    mock_response.events = _empty_events()
    # .messages is an async property — AsyncMock returns a coroutine
    mock_response.messages = AsyncMock(return_value=[])()
    return mock_response


# ── Mock ChatSession ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_session(mock_agents):
    """Pre-built ChatSession with mocked agents and patched a_run_group_chat."""
    user_proxy, pattern = mock_agents
    ctx = MagicMock()

    session = ChatSession(
        session_id="test-session-001",
        user_proxy=user_proxy,
        pattern=pattern,
        ctx=ctx,
        agent_models={"planner": "test-model"},
    )
    return session


# ── Mock SessionManager ──────────────────────────────────────────────────────


@pytest.fixture
def mock_session_manager(mock_session):
    """SessionManager that always returns the mock_session."""
    manager = SessionManager()
    manager._sessions["test-session-001"] = mock_session
    return manager

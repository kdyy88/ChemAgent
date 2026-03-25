"""
Shared test fixtures for ChemAgent backend tests.

Provides mock LLM config, agent pairs, and session fixtures so that
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


# ── Mock agent pair ───────────────────────────────────────────────────────────


@pytest.fixture
def mock_agents():
    """Return a (brain, executor) pair with mocked a_run().

    Each a_run() call returns an AsyncRunResponseProtocol-like object
    whose .events is an empty async iterable.
    """
    brain = MagicMock()
    brain.name = "chem_brain"

    executor = MagicMock()
    executor.name = "executor"

    async def _empty_events():
        return
        yield  # make it an async generator  # noqa: E501

    mock_response = MagicMock()
    mock_response.events = _empty_events()

    executor.a_run = AsyncMock(return_value=mock_response)

    return brain, executor


# ── Mock ChatSession ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_session(mock_agents):
    """Pre-built ChatSession with mocked agents."""
    brain, executor = mock_agents
    return ChatSession(
        session_id="test-session-001",
        brain=brain,
        executor=executor,
        agent_models={"chem_brain": "test-model"},
    )


# ── Mock SessionManager ──────────────────────────────────────────────────────


@pytest.fixture
def mock_session_manager(mock_session):
    """SessionManager that always returns the mock_session."""
    manager = SessionManager()
    manager._sessions["test-session-001"] = mock_session
    return manager

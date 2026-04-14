from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.config import is_parameter_compatible_model
from app.api.v1 import chat as sse_chat


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(sse_chat.router, prefix="/api/v1/chat")
    return TestClient(app)


def test_list_models_returns_provider_catalog(monkeypatch) -> None:
    async def fake_fetch_available_models():
        return (
            [
                {
                    "id": "gpt-5.2",
                    "label": "gpt-5.2",
                    "is_default": True,
                    "is_reasoning": True,
                    "max_context_tokens": 400000,
                },
                {
                    "id": "gpt-5-mini",
                    "label": "gpt-5-mini",
                    "is_default": False,
                    "is_reasoning": True,
                    "max_context_tokens": 400000,
                },
            ],
            None,
        )

    monkeypatch.setattr(sse_chat, "fetch_available_models", fake_fetch_available_models)
    client = _build_client()

    response = client.get("/api/v1/chat/models")

    assert response.status_code == 200
    assert response.json() == {
        "source": "provider",
        "models": [
            {
                "id": "gpt-5.2",
                "label": "gpt-5.2",
                "is_default": True,
                "is_reasoning": True,
                "max_context_tokens": 400000,
            },
            {
                "id": "gpt-5-mini",
                "label": "gpt-5-mini",
                "is_default": False,
                "is_reasoning": True,
                "max_context_tokens": 400000,
            },
        ],
        "warning": None,
    }


def test_stream_chat_forwards_selected_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, session_id: str, turn_id: str):
            captured["session_id"] = session_id
            captured["turn_id"] = turn_id

        async def submit_message(self, **kwargs) -> AsyncGenerator[str, None]:
            captured.update(kwargs)
            yield 'data: {"type":"done","session_id":"session-1","turn_id":"turn-1"}\n\n'

    monkeypatch.setattr(sse_chat, "ChemSessionEngine", FakeEngine)
    client = _build_client()

    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={
            "message": "Analyze aspirin",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "model": "gpt-5.2",
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert '"type":"done"' in body
    assert captured["session_id"] == "session-1"
    assert captured["turn_id"] == "turn-1"
    assert captured["model"] == "gpt-5.2"
    assert captured["message"] == "Analyze aspirin"


def test_model_catalog_whitelist_only_keeps_gpt_reasoning_models() -> None:
    assert is_parameter_compatible_model("gpt-5.2") is True
    assert is_parameter_compatible_model("gpt-5-mini") is True
    assert is_parameter_compatible_model("gpt-4o") is False
    assert is_parameter_compatible_model("o3") is False
    assert is_parameter_compatible_model("claude-3-7-sonnet") is False
    assert is_parameter_compatible_model("text-embedding-3-large") is False


def test_poll_pending_jobs_streams_engine_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, session_id: str, turn_id: str):
            captured["session_id"] = session_id
            captured["turn_id"] = turn_id

        async def poll_pending_jobs(self) -> AsyncGenerator[str, None]:
            yield 'data: {"type":"done","session_id":"session-1","turn_id":"turn-poll"}\n\n'

    monkeypatch.setattr(sse_chat, "ChemSessionEngine", FakeEngine)
    client = _build_client()

    with client.stream(
        "POST",
        "/api/v1/chat/pending/poll",
        json={"session_id": "session-1", "turn_id": "turn-poll"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert '"type":"done"' in body
    assert captured["session_id"] == "session-1"
    assert captured["turn_id"] == "turn-poll"


def test_mvp_conformer_smoke_streams_engine_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, session_id: str, turn_id: str):
            captured["session_id"] = session_id
            captured["turn_id"] = turn_id

        async def run_mvp_conformer_smoke(self, **kwargs) -> AsyncGenerator[str, None]:
            captured.update(kwargs)
            yield 'data: {"type":"job.started","session_id":"session-1","turn_id":"turn-mvp"}\n\n'
            yield 'data: {"type":"done","session_id":"session-1","turn_id":"turn-mvp"}\n\n'

    monkeypatch.setattr(sse_chat, "ChemSessionEngine", FakeEngine)
    client = _build_client()

    with client.stream(
        "POST",
        "/api/v1/chat/mvp/conformer",
        json={"session_id": "session-1", "turn_id": "turn-mvp", "smiles": "CCO", "name": "ethanol"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert '"type":"job.started"' in body
    assert captured["smiles"] == "CCO"
    assert captured["name"] == "ethanol"


def test_get_workspace_snapshot_returns_projection(monkeypatch) -> None:
    snapshot = MagicMock()
    snapshot.values = {
        "workspace_projection": {
            "project_id": "session-1",
            "workspace_id": "ws_123",
            "version": 4,
            "scenario_kind": "scaffold_hop_mvp",
            "root_handle": "root_molecule",
            "candidate_handles": ["candidate_1", "candidate_2", "candidate_3"],
            "active_view_id": "active_view",
            "nodes": {},
            "relations": {},
            "handle_bindings": {},
            "viewport": {"focused_handles": ["root_molecule"]},
            "rules": [],
            "async_jobs": {},
        },
        "pending_worker_tasks": [{"task_id": "task_1"}],
    }

    monkeypatch.setattr(sse_chat, "has_persisted_session", AsyncMock(return_value=True))
    monkeypatch.setattr(sse_chat, "get_compiled_graph", lambda: MagicMock(aget_state=AsyncMock(return_value=snapshot)))
    client = _build_client()

    response = client.get("/api/v1/chat/workspace/session-1")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "session-1"
    assert body["version"] == 4
    assert body["pending_job_count"] == 1


def test_get_workspace_events_returns_buffered_events(monkeypatch) -> None:
    snapshot = MagicMock()
    snapshot.values = {
        "workspace_projection": {
            "project_id": "session-1",
            "workspace_id": "ws_123",
            "version": 2,
            "scenario_kind": None,
            "root_handle": None,
            "candidate_handles": [],
            "active_view_id": None,
            "nodes": {},
            "relations": {},
            "handle_bindings": {},
            "viewport": {"focused_handles": []},
            "rules": [],
            "async_jobs": {},
        },
        "workspace_events": [{"type": "job.started", "job_id": "job_1"}],
        "pending_worker_tasks": [],
    }

    monkeypatch.setattr(sse_chat, "has_persisted_session", AsyncMock(return_value=True))
    monkeypatch.setattr(sse_chat, "get_compiled_graph", lambda: MagicMock(aget_state=AsyncMock(return_value=snapshot)))
    client = _build_client()

    response = client.get("/api/v1/chat/workspace/session-1/events")

    assert response.status_code == 200
    assert response.json()["events"] == [{"type": "job.started", "job_id": "job_1"}]


def test_approve_modify_rejects_non_whitelisted_args(monkeypatch) -> None:
    class FakeEngine:
        def __init__(self, session_id: str, turn_id: str):
            self.session_id = session_id
            self.turn_id = turn_id

        async def resume_approval(self, **kwargs):
            yield 'data: {"type":"done"}\n\n'

    monkeypatch.setattr(sse_chat, "ChemSessionEngine", FakeEngine)
    client = _build_client()

    response = client.post(
        "/api/v1/chat/approve",
        json={
            "session_id": "session-1",
            "turn_id": "turn-1",
            "action": "modify",
            "modify_args": {"ph": 7.4},
        },
    )

    assert response.status_code == 422
    assert "Unsupported modify args" in response.json()["detail"]
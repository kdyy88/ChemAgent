from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.config import is_parameter_compatible_model
from app.api import sse_chat


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(sse_chat.router, prefix="/api/chat")
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

    response = client.get("/api/chat/models")

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
        "/api/chat/stream",
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
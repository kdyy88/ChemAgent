from __future__ import annotations

import json
import time

import pytest
from langchain_core.tools import tool

from app.agents.decorators import safe_chem_tool


def _mock_crash() -> str:
    raise ValueError("Mock Error")


def _mock_infinite() -> str:
    while True:
        time.sleep(0.05)


@safe_chem_tool(timeout=3)
def _safe_mock_crash() -> str:
    return _mock_crash()


@safe_chem_tool(timeout=0.2)
def _safe_mock_infinite() -> str:
    return _mock_infinite()


@safe_chem_tool(timeout=0.2)
async def _safe_async_crash() -> str:
    raise ValueError("Async Mock Error")


@tool
@safe_chem_tool(timeout=1.0)
def _tool_mock_crash(smiles: str) -> str:
    """Raise a deterministic error so the LangChain tool wrapper can be tested."""
    raise ValueError(f"invalid smiles: {smiles}")


def test_safe_chem_tool_converts_sync_exception_to_error_payload() -> None:
    payload = json.loads(_safe_mock_crash())

    assert payload["status"] == "error"
    assert payload["error_boundary"] == "safe_chem_tool"
    assert payload["error_type"] == "ValueError"
    assert payload["details"] == "Mock Error"
    assert payload["error"].startswith("[Execution Failed]")
    assert "Suggestion for Agent:" in payload["error"]


def test_safe_chem_tool_times_out_sync_function() -> None:
    payload = json.loads(_safe_mock_infinite())

    assert payload["status"] == "error"
    assert payload["error_type"] == "TimeoutException"
    assert "Execution exceeded 0.2s timeout." in payload["details"]
    assert payload["error"].startswith("[Execution Failed]")


@pytest.mark.asyncio
async def test_safe_chem_tool_converts_async_exception_to_error_payload() -> None:
    payload = json.loads(await _safe_async_crash())

    assert payload["status"] == "error"
    assert payload["error_type"] == "ValueError"
    assert payload["details"] == "Async Mock Error"


@pytest.mark.asyncio
async def test_safe_chem_tool_preserves_langchain_tool_compatibility() -> None:
    payload = json.loads(await _tool_mock_crash.ainvoke({"smiles": "C1=CC=C"}))

    assert payload["status"] == "error"
    assert payload["tool_name"] == "_tool_mock_crash"
    assert payload["error_type"] == "ValueError"
    assert "invalid smiles" in payload["details"].lower()
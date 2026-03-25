"""
Unit tests for chem_tools — retry, worker offloading, error handling.

These tests mock HTTP calls and RDKit operations so they run without
network or heavy dependencies.
"""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.chem_tools import (
    _fetch_smiles_from_pubchem,
    _offload,
    _slim_response,
    get_molecule_smiles,
)
from app.core.tooling import ToolExecutionResult


# ── _slim_response ────────────────────────────────────────────────────────────


class TestSlimResponse:
    def test_success_result(self):
        result = ToolExecutionResult(
            status="success",
            summary="Found aspirin",
            data={"smiles": "CC(=O)OC1=CC=CC=C1C(=O)O"},
        )
        slim = json.loads(_slim_response(result))
        assert slim["success"] is True
        assert slim["summary"] == "Found aspirin"
        assert "result_id" in slim

    def test_error_result_with_retry_hint(self):
        result = ToolExecutionResult(
            status="error",
            summary="Not found",
            data={},
            error_code="compound_not_found",
            retry_hint="Check spelling",
        )
        slim = json.loads(_slim_response(result))
        assert slim["success"] is False
        assert slim["error_code"] == "compound_not_found"
        assert slim["retry_hint"] == "Check spelling"


# ── _fetch_smiles_from_pubchem ────────────────────────────────────────────────


class TestFetchSmiles:
    @patch("app.tools.chem_tools.urllib.request.urlopen")
    def test_returns_smiles_on_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "PropertyTable": {
                "Properties": [{"IsomericSMILES": "CC(=O)OC1=CC=CC=C1C(=O)O"}]
            }
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _fetch_smiles_from_pubchem("aspirin")
        assert result == "CC(=O)OC1=CC=CC=C1C(=O)O"

    @patch("app.tools.chem_tools.urllib.request.urlopen")
    def test_returns_none_on_404(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=404, msg="Not Found", hdrs={}, fp=None  # type: ignore
        )
        result = _fetch_smiles_from_pubchem("nonexistent_compound_xyz")
        assert result is None


# ── _offload ──────────────────────────────────────────────────────────────────


class TestOffload:
    @pytest.mark.asyncio
    async def test_fallback_uses_task_dispatch(self):
        mock_fn = MagicMock(return_value={"is_valid": True, "result": "ok"})
        with patch("app.tools.chem_tools.USE_WORKER", False):
            with patch.dict(
                "app.worker._TASK_DISPATCH",
                {"rdkit.test_task": mock_fn},
            ):
                result = await _offload("rdkit.test_task", {"smiles": "CCO"})
                assert result["is_valid"] is True
                mock_fn.assert_called_once_with(smiles="CCO")

    @pytest.mark.asyncio
    async def test_unknown_task_returns_error(self):
        with patch("app.tools.chem_tools.USE_WORKER", False):
            result = await _offload("rdkit.nonexistent", {})
            assert result["is_valid"] is False
            assert "Unknown task" in result["error"]


# ── get_molecule_smiles ───────────────────────────────────────────────────────


class TestGetMoleculeSmiles:
    @patch("app.tools.chem_tools._fetch_smiles_from_pubchem")
    def test_success(self, mock_fetch):
        mock_fetch.return_value = "CCO"
        raw = get_molecule_smiles("ethanol")
        result = json.loads(raw)
        assert result["success"] is True
        assert "CCO" in result["summary"]

    @patch("app.tools.chem_tools._fetch_smiles_from_pubchem")
    def test_not_found(self, mock_fetch):
        mock_fetch.return_value = None
        raw = get_molecule_smiles("xyznonexistent")
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error_code"] == "compound_not_found"

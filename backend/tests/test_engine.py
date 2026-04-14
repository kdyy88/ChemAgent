"""Unit tests for ChemSessionEngine (双层生成器架构).

Tests cover:
- SSE serialization helpers
- _extract_stream_text / _sanitize_tool_output module-level functions
- _intercept_and_collapse_artifact (Artifact Pointer / data-plane isolation)
- _withheld_error_message (Error Withholding)
- _parse_langgraph_event (LangGraph→dict translation)
- submit_message outer loop (mocked graph — no LLM required)
"""

from __future__ import annotations

import json
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.main_agent.engine import (
    ChemSessionEngine,
    _WITHHELD_ERROR_KEYWORDS,
    _extract_stream_text,
    _sanitize_tool_output,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def engine() -> ChemSessionEngine:
    return ChemSessionEngine(session_id="sess-test", turn_id="turn-001")


# ── SSE helpers ───────────────────────────────────────────────────────────────

class TestSseHelper:
    def test_sse_is_valid_data_line(self, engine: ChemSessionEngine) -> None:
        result = engine._sse({"type": "token", "content": "hello"})
        assert result.startswith("data: ")
        assert result.endswith("\n\n")

    def test_sse_round_trips_payload(self, engine: ChemSessionEngine) -> None:
        payload = {"type": "done", "session_id": "sess-test"}
        line = engine._sse(payload)
        body = line.removeprefix("data: ").strip()
        assert json.loads(body) == payload

    def test_sse_preserves_non_ascii(self, engine: ChemSessionEngine) -> None:
        payload = {"type": "thinking", "text": "正在计算分子量..."}
        line = engine._sse(payload)
        body = line.removeprefix("data: ").strip()
        assert json.loads(body)["text"] == "正在计算分子量..."


# ── _extract_stream_text ──────────────────────────────────────────────────────

class TestExtractStreamText:
    def _fake_chunk(self, **kwargs):
        chunk = MagicMock()
        for k, v in kwargs.items():
            setattr(chunk, k, v)
        return chunk

    def test_plain_string_content(self) -> None:
        chunk = self._fake_chunk(additional_kwargs={})
        token, reasoning = _extract_stream_text("hello world", chunk)
        assert token == "hello world"
        assert reasoning == ""

    def test_text_block_dict(self) -> None:
        chunk = self._fake_chunk(additional_kwargs={})
        token, reasoning = _extract_stream_text({"type": "text", "text": "aspirin"}, chunk)
        assert token == "aspirin"
        assert reasoning == ""

    def test_reasoning_block_dict(self) -> None:
        chunk = self._fake_chunk(additional_kwargs={})
        token, reasoning = _extract_stream_text(
            {"type": "reasoning", "text": "thinking..."},
            chunk,
        )
        assert token == ""
        assert reasoning == "thinking..."

    def test_thinking_block_dict(self) -> None:
        chunk = self._fake_chunk(additional_kwargs={})
        token, reasoning = _extract_stream_text(
            {"type": "thinking", "thinking": "chain of thought"},
            chunk,
        )
        assert reasoning == "chain of thought"

    def test_additional_kwargs_reasoning(self) -> None:
        chunk = self._fake_chunk(additional_kwargs={"reasoning_content": "deep thought"})
        token, reasoning = _extract_stream_text("", chunk)
        assert reasoning == "deep thought"

    def test_list_content_with_reasoning_and_text(self) -> None:
        chunk = self._fake_chunk(additional_kwargs={})
        content = [
            {"type": "reasoning", "text": "step 1"},
            {"type": "text", "text": "answer"},
        ]
        token, reasoning = _extract_stream_text(content, chunk)
        assert token == "answer"
        assert reasoning == "step 1"

    def test_empty_string_returns_empty(self) -> None:
        chunk = self._fake_chunk(additional_kwargs={})
        token, reasoning = _extract_stream_text("", chunk)
        assert token == ""
        assert reasoning == ""


# ── _sanitize_tool_output ─────────────────────────────────────────────────────

class TestSanitizeToolOutput:
    def test_removes_image_key(self) -> None:
        output = {"smiles": "CC", "image": "data:image/png;base64,AAAA"}
        sanitized = _sanitize_tool_output("render_smiles", output)
        assert "image" not in sanitized
        assert sanitized["smiles"] == "CC"

    def test_removes_sdf_content(self) -> None:
        output = {"name": "aspirin", "sdf_content": "\n  Mrv2211\n..."}
        sanitized = _sanitize_tool_output("build_3d_conformer", output)
        assert "sdf_content" not in sanitized
        assert "artifact_payloads_removed" in sanitized
        assert "sdf_content" in sanitized["artifact_payloads_removed"]

    def test_passes_through_non_bulky_output(self) -> None:
        output = {"molecular_weight": 180.16, "formula": "C6H12O6"}
        sanitized = _sanitize_tool_output("compute_mol_properties", output)
        assert sanitized == output

    def test_non_dict_output_passthrough(self) -> None:
        assert _sanitize_tool_output("any_tool", "plain string") == "plain string"

    def test_truncates_long_convert_format_output(self) -> None:
        long_sdf = "M  END\n" * 300  # > 500 chars
        output = {"output": long_sdf, "output_format": "sdf"}
        sanitized = _sanitize_tool_output("tool_convert_format", output)
        assert len(sanitized["output"]) < 200  # replaced with short message


# ── _intercept_and_collapse_artifact ─────────────────────────────────────────

class TestInterceptAndCollapseArtifact:
    async def test_collapses_pdbqt_content(self, engine: ChemSessionEngine) -> None:
        big_pdbqt = "ATOM   1..." * 500
        event = {
            "type": "tool_end",
            "tool": "prepare_pdbqt",
            "output": {"pdbqt_content": big_pdbqt, "status": "ok"},
        }
        with patch("app.agents.main_agent.engine.store_engine_artifact", new_callable=AsyncMock) as m:
            result = await engine._intercept_and_collapse_artifact(event)
        output = result["output"]

        assert "pdbqt_content" not in output
        assert "pdbqt_content_artifact_id" in output
        artifact_id = output["pdbqt_content_artifact_id"]
        assert artifact_id.startswith("art_")
        m.assert_called_once_with(artifact_id, big_pdbqt)
        assert "system_notice" in output

    async def test_collapses_sdf_content(self, engine: ChemSessionEngine) -> None:
        event = {
            "type": "tool_end",
            "tool": "build_3d_conformer",
            "output": {"sdf_content": "\n  Mrv\n...", "name": "caffeine"},
        }
        with patch("app.agents.main_agent.engine.store_engine_artifact", new_callable=AsyncMock) as m:
            result = await engine._intercept_and_collapse_artifact(event)
        assert "sdf_content" not in result["output"]
        assert m.called

    async def test_does_not_modify_non_bulky_output(self, engine: ChemSessionEngine) -> None:
        event = {
            "type": "tool_end",
            "tool": "compute_mol_properties",
            "output": {"mw": 194.19, "hbd": 0},
        }
        with patch("app.agents.main_agent.engine.store_engine_artifact", new_callable=AsyncMock) as m:
            result = await engine._intercept_and_collapse_artifact(event)
        assert result["output"] == {"mw": 194.19, "hbd": 0}
        m.assert_not_called()

    async def test_non_dict_output_left_unchanged(self, engine: ChemSessionEngine) -> None:
        event = {"type": "tool_end", "tool": "any", "output": "ok"}
        with patch("app.agents.main_agent.engine.store_engine_artifact", new_callable=AsyncMock):
            result = await engine._intercept_and_collapse_artifact(event)
        assert result["output"] == "ok"

    async def test_multiple_artifacts_each_get_unique_id(self, engine: ChemSessionEngine) -> None:
        event = {
            "type": "tool_end",
            "tool": "some_tool",
            "output": {
                "pdbqt_content": "ATOM 1",
                "sdf_content": "\n  Mrv\n",
            },
        }
        with patch("app.agents.main_agent.engine.store_engine_artifact", new_callable=AsyncMock) as m:
            result = await engine._intercept_and_collapse_artifact(event)
        assert m.call_count == 2
        ids = {v for k, v in result["output"].items() if k.endswith("_artifact_id")}
        assert len(ids) == 2


# ── _withheld_error_message ───────────────────────────────────────────────────

class TestWithheldErrorMessage:
    @pytest.mark.parametrize("keyword", list(_WITHHELD_ERROR_KEYWORDS))
    def test_known_chemical_error_keywords(
        self, engine: ChemSessionEngine, keyword: str
    ) -> None:
        event = {
            "type": "tool_end",
            "output": {"error": f"RDKit: {keyword} error in atom 2"},
        }
        assert engine._withheld_error_message(event) is not None

    def test_generic_error_not_withheld(self, engine: ChemSessionEngine) -> None:
        event = {
            "type": "tool_end",
            "output": {"error": "network timeout"},
        }
        assert engine._withheld_error_message(event) is None

    def test_non_tool_end_event_not_withheld(self, engine: ChemSessionEngine) -> None:
        event = {
            "type": "error",
            "output": {"error": "invalid smiles: CC(C)(C)(C)C"},
        }
        assert engine._withheld_error_message(event) is None

    def test_tool_end_without_error_key(self, engine: ChemSessionEngine) -> None:
        event = {"type": "tool_end", "output": {"mw": 180.16}}
        assert engine._withheld_error_message(event) is None

    def test_tool_end_with_non_dict_output(self, engine: ChemSessionEngine) -> None:
        event = {"type": "tool_end", "output": "ok"}
        assert engine._withheld_error_message(event) is None

    def test_returns_original_error_string(self, engine: ChemSessionEngine) -> None:
        msg = "Explicit valence for atom # 0 C, 5, is greater than permitted"
        event = {"type": "tool_end", "output": {"error": msg}}
        result = engine._withheld_error_message(event)
        assert result == msg


# ── _parse_langgraph_event ────────────────────────────────────────────────────

class TestParseLanggraphEvent:
    def _chunk_with_content(self, content):
        chunk = MagicMock()
        chunk.content = content
        chunk.additional_kwargs = {}
        return chunk

    def test_token_event_emitted_for_streaming_node(
        self, engine: ChemSessionEngine
    ) -> None:
        chunk = self._chunk_with_content("aspirin")
        event = {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "chem_agent"},
            "data": {"chunk": chunk},
        }
        results = engine._parse_langgraph_event(event)
        tokens = [r for r in results if r["type"] == "token"]
        assert len(tokens) == 1
        assert tokens[0]["content"] == "aspirin"

    def test_token_event_not_emitted_for_non_streaming_node(
        self, engine: ChemSessionEngine
    ) -> None:
        chunk = self._chunk_with_content("hello")
        event = {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "planner_node"},
            "data": {"chunk": chunk},
        }
        results = engine._parse_langgraph_event(event)
        tokens = [r for r in results if r["type"] == "token"]
        assert len(tokens) == 0

    def test_node_start_emitted_for_lifecycle_node(
        self, engine: ChemSessionEngine
    ) -> None:
        event = {
            "event": "on_chain_start",
            "name": "chem_agent",
            "metadata": {"langgraph_node": "chem_agent"},
            "data": {},
        }
        results = engine._parse_langgraph_event(event)
        starts = [r for r in results if r["type"] == "node_start"]
        assert len(starts) == 1
        assert starts[0]["node"] == "chem_agent"

    def test_node_end_emitted(self, engine: ChemSessionEngine) -> None:
        event = {
            "event": "on_chain_end",
            "name": "planner_node",
            "metadata": {"langgraph_node": "planner_node"},
            "data": {},
        }
        results = engine._parse_langgraph_event(event)
        ends = [r for r in results if r["type"] == "node_end"]
        assert len(ends) == 1

    def test_tools_executor_chain_end_emits_workspace_events(
        self, engine: ChemSessionEngine
    ) -> None:
        event = {
            "event": "on_chain_end",
            "name": "tools_executor",
            "metadata": {"langgraph_node": "tools_executor"},
            "data": {
                "output": {
                    "workspace_events": [
                        {"type": "workspace.delta", "scope": "graph", "version": 3},
                        {"type": "molecule.upserted", "node_id": "mol_root", "handle": "root_molecule"},
                    ]
                }
            },
        }
        results = engine._parse_langgraph_event(event)
        assert any(r["type"] == "node_end" for r in results)
        assert any(r["type"] == "workspace.delta" and r["scope"] == "graph" for r in results)
        assert any(r["type"] == "molecule.upserted" and r["node_id"] == "mol_root" for r in results)

    def test_golden_scenario_chain_end_emits_assistant_message_and_workspace_events(
        self, engine: ChemSessionEngine
    ) -> None:
        event = {
            "event": "on_chain_end",
            "name": "golden_scenario",
            "metadata": {"langgraph_node": "golden_scenario"},
            "data": {
                "output": {
                    "messages": [{"content": "Golden-path MVP workflow started."}],
                    "workspace_events": [
                        {"type": "workspace.delta", "version": 7},
                        {"type": "job.started", "job_id": "job_candidate_1_conf"},
                    ],
                }
            },
        }
        results = engine._parse_langgraph_event(event)
        assert any(r["type"] == "assistant.message" and "Golden-path" in r["content"] for r in results)
        assert any(r["type"] == "workspace.delta" for r in results)
        assert any(r["type"] == "job.started" for r in results)

    def test_tool_start_event(self, engine: ChemSessionEngine) -> None:
        event = {
            "event": "on_tool_start",
            "name": "validate_smiles",
            "metadata": {"langgraph_node": "chem_agent"},
            "data": {"input": {"smiles": "CC"}},
        }
        results = engine._parse_langgraph_event(event)
        tool_starts = [r for r in results if r["type"] == "tool_start"]
        assert len(tool_starts) == 1
        assert tool_starts[0]["tool"] == "validate_smiles"

    def test_tool_end_event(self, engine: ChemSessionEngine) -> None:
        event = {
            "event": "on_tool_end",
            "name": "compute_mol_properties",
            "metadata": {"langgraph_node": "chem_agent"},
            "data": {"output": json.dumps({"mw": 180.16})},
        }
        results = engine._parse_langgraph_event(event)
        tool_ends = [r for r in results if r["type"] == "tool_end"]
        assert len(tool_ends) == 1
        assert tool_ends[0]["tool"] == "compute_mol_properties"

    def test_silent_tool_not_emitted(self, engine: ChemSessionEngine) -> None:
        event = {
            "event": "on_tool_start",
            "name": "tool_update_task_status",
            "metadata": {},
            "data": {"input": {}},
        }
        results = engine._parse_langgraph_event(event)
        assert results == []

    def test_unknown_event_yields_nothing(self, engine: ChemSessionEngine) -> None:
        event = {
            "event": "on_something_unknown",
            "name": "foo",
            "metadata": {},
            "data": {},
        }
        assert engine._parse_langgraph_event(event) == []

    def test_custom_thinking_event(self, engine: ChemSessionEngine) -> None:
        event = {
            "event": "on_custom_event",
            "name": "thinking",
            "metadata": {},
            "data": {"text": "analyzing molecule", "source": "chem_agent"},
        }
        results = engine._parse_langgraph_event(event)
        assert len(results) == 1
        assert results[0]["type"] == "thinking"
        assert results[0]["text"] == "analyzing molecule"


# ── submit_message outer loop (mocked graph) ─────────────────────────────────

def _make_mock_graph(events: list[dict]) -> MagicMock:
    """Build a mock compiled graph that yields the given astream_events sequence."""

    async def _fake_astream(*_args, **_kwargs) -> AsyncGenerator[dict, None]:
        for e in events:
            yield e

    snapshot = MagicMock()
    snapshot.interrupts = []
    snapshot.config = {"configurable": {"checkpoint_id": "chk-abc"}}

    graph = MagicMock()
    graph.astream_events = _fake_astream
    graph.aget_state = AsyncMock(return_value=snapshot)
    return graph


@pytest.mark.asyncio
class TestSubmitMessageOuterLoop:
    async def _collect(self, engine: ChemSessionEngine, **kwargs) -> list[dict]:
        """Collect all SSE events as parsed dicts."""
        events: list[dict] = []
        async for line in engine.submit_message(**kwargs):
            body = line.removeprefix("data: ").strip()
            events.append(json.loads(body))
        return events

    async def _collect_resume(self, engine: ChemSessionEngine, **kwargs) -> list[dict]:
        events: list[dict] = []
        async for line in engine.resume_approval(**kwargs):
            body = line.removeprefix("data: ").strip()
            events.append(json.loads(body))
        return events

    async def test_emits_run_started_and_done(self, engine: ChemSessionEngine) -> None:
        mock_graph = _make_mock_graph([])

        with (
            patch("app.agents.main_agent.engine.get_compiled_graph", return_value=mock_graph),
            patch("app.agents.main_agent.engine.has_persisted_session", new_callable=AsyncMock, return_value=False),
        ):
            events = await self._collect(engine, message="Hello", history=None)

        types = [e["type"] for e in events]
        assert "run_started" in types
        assert "done" in types
        # run_started must come before done
        assert types.index("run_started") < types.index("done")

    async def test_token_events_forwarded(self, engine: ChemSessionEngine) -> None:
        chunk = MagicMock()
        chunk.content = "carbon"
        chunk.additional_kwargs = {}

        lg_event = {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "chem_agent"},
            "data": {"chunk": chunk},
        }
        mock_graph = _make_mock_graph([lg_event])

        with (
            patch("app.agents.main_agent.engine.get_compiled_graph", return_value=mock_graph),
            patch("app.agents.main_agent.engine.has_persisted_session", new_callable=AsyncMock, return_value=False),
        ):
            events = await self._collect(engine, message="draw carbon")

        tokens = [e for e in events if e["type"] == "token"]
        assert len(tokens) == 1
        assert tokens[0]["content"] == "carbon"

    async def test_workspace_events_are_forwarded_from_tools_executor(
        self, engine: ChemSessionEngine
    ) -> None:
        lg_event = {
            "event": "on_chain_end",
            "name": "tools_executor",
            "metadata": {"langgraph_node": "tools_executor"},
            "data": {
                "output": {
                    "workspace_events": [
                        {"type": "workspace.delta", "scope": "graph", "version": 1},
                        {"type": "viewport.changed", "focused_handles": ["root_molecule"], "reference_handle": "root_molecule"},
                    ]
                }
            },
        }
        mock_graph = _make_mock_graph([lg_event])

        with (
            patch("app.agents.main_agent.engine.get_compiled_graph", return_value=mock_graph),
            patch("app.agents.main_agent.engine.has_persisted_session", new_callable=AsyncMock, return_value=False),
        ):
            events = await self._collect(engine, message="render workspace")

        assert any(event["type"] == "workspace.delta" for event in events)
        assert any(event["type"] == "viewport.changed" for event in events)

    async def test_workspace_events_are_forwarded_from_chem_agent(
        self, engine: ChemSessionEngine
    ) -> None:
        lg_event = {
            "event": "on_chain_end",
            "name": "chem_agent",
            "metadata": {"langgraph_node": "chem_agent"},
            "data": {
                "output": {
                    "workspace_events": [
                        {"type": "job.completed", "job_id": "job_1", "status": "completed"},
                    ]
                }
            },
        }
        mock_graph = _make_mock_graph([lg_event])

        with (
            patch("app.agents.main_agent.engine.get_compiled_graph", return_value=mock_graph),
            patch("app.agents.main_agent.engine.has_persisted_session", new_callable=AsyncMock, return_value=False),
        ):
            events = await self._collect(engine, message="render workspace")

        assert any(event["type"] == "job.completed" and event.get("job_id") == "job_1" for event in events)
        

    async def test_poll_pending_jobs_updates_checkpoint_and_streams_results(
        self, engine: ChemSessionEngine
    ) -> None:
        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=MagicMock(
                values={"pending_worker_tasks": [{"task_id": "task_1"}]},
                config={"configurable": {"checkpoint_id": "cp-1"}},
            )
        )
        mock_graph.aupdate_state = AsyncMock()

        async def _fake_drain(state, config):
            return {
                "messages": [],
                "artifacts": [{"kind": "conformer_sdf", "artifact_id": "art_1"}],
                "workspace_events": [{"type": "job.completed", "job_id": "job_1", "status": "completed"}],
                "workspace_projection": {"project_id": "sess-test", "workspace_id": "ws_1", "version": 2, "nodes": {}, "relations": {}, "handle_bindings": {}, "viewport": {"focused_handles": [], "reference_handle": None}, "rules": [], "async_jobs": {}},
                "pending_worker_tasks": [],
                "tool_events": [{"tool_name": "tool_build_3d_conformer", "output": {"status": "success"}}],
            }

        with (
            patch("app.agents.main_agent.engine.get_compiled_graph", return_value=mock_graph),
            patch("app.agents.main_agent.engine.has_persisted_session", new_callable=AsyncMock, return_value=True),
            patch("app.agents.main_agent.engine.drain_pending_worker_tasks", new=_fake_drain),
        ):
            events = [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in engine.poll_pending_jobs()]

        mock_graph.aupdate_state.assert_awaited_once()
        assert any(event["type"] == "job.completed" for event in events)
        assert any(event["type"] == "artifact" for event in events)
        assert any(event["type"] == "tool_end" for event in events)
        assert events[-1]["type"] == "done"

    async def test_run_mvp_conformer_smoke_streams_job_lifecycle(
        self, engine: ChemSessionEngine
    ) -> None:
        with (
            patch(
                "app.agents.main_agent.engine.submit_task_to_worker",
                new=AsyncMock(return_value={
                    "task_id": "task_mvp_1",
                    "task_name": "babel.build_3d_conformer",
                    "status": "queued",
                    "result": {},
                    "task_context": {},
                    "delivery": "worker",
                    "fallback_reason": "",
                }),
            ),
            patch(
                "app.agents.main_agent.engine.wait_for_task_result",
                new=AsyncMock(return_value={
                    "task_id": "task_mvp_1",
                    "task_name": "babel.build_3d_conformer",
                    "status": "completed",
                    "result": {
                        "is_valid": True,
                        "smiles": "CCO",
                        "name": "ethanol",
                        "sdf_content": "mock-sdf",
                        "energy_kcal_mol": -7.2,
                    },
                    "task_context": {},
                    "delivery": "worker",
                    "fallback_reason": "",
                }),
            ),
        ):
            events = [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in engine.run_mvp_conformer_smoke(smiles="CCO", name="ethanol")]

        assert any(event["type"] == "tool_start" and event.get("tool") == "tool_build_3d_conformer" for event in events)
        assert any(event["type"] == "job.started" for event in events)
        assert any(event["type"] == "job.progress" for event in events)
        assert any(event["type"] == "artifact" and event.get("kind") == "conformer_sdf" for event in events)
        assert any(event["type"] == "job.completed" for event in events)
        assert events[-1]["type"] == "done"

    async def test_artifact_pointer_replaces_large_field(
        self, engine: ChemSessionEngine
    ) -> None:
        """Verify that pdbqt_content never reaches the SSE output.

        Processing pipeline:
            1. _parse_langgraph_event → _sanitize_tool_output strips keys in
               _BULKY_TOOL_OUTPUT_KEYS (includes pdbqt_content) and records
               them in 'artifact_payloads_removed'.
            2. _intercept_and_collapse_artifact checks _ARTIFACT_COLLAPSE_KEYS;
               if the key is already absent, nothing is stored in the registry.

        Net result: pdbqt_content is absent from the tool_end SSE frame and
        'artifact_payloads_removed' signals that it was stripped.
        """
        big_pdbqt = "ATOM  " * 2000
        raw_tool_end = {
            "event": "on_tool_end",
            "name": "prepare_pdbqt",
            "metadata": {},
            "data": {"output": json.dumps({"pdbqt_content": big_pdbqt, "status": "ok"})},
        }
        mock_graph = _make_mock_graph([raw_tool_end])

        with (
            patch("app.agents.main_agent.engine.get_compiled_graph", return_value=mock_graph),
            patch("app.agents.main_agent.engine.has_persisted_session", new_callable=AsyncMock, return_value=False),
        ):
            events = await self._collect(engine, message="prepare pdbqt")

        tool_ends = [e for e in events if e["type"] == "tool_end"]
        assert len(tool_ends) == 1
        output = tool_ends[0]["output"]
        # Raw content must not appear in control-plane SSE
        assert "pdbqt_content" not in output
        # _sanitize_tool_output records what it stripped
        assert "artifact_payloads_removed" in output
        assert "pdbqt_content" in output["artifact_payloads_removed"]

    async def test_withheld_error_triggers_retry_thinking(
        self, engine: ChemSessionEngine
    ) -> None:
        """
        A tool_end with a valence error must trigger error withholding:
        - no 'error' SSE event visible to the user
        - a 'thinking' self-correction event is emitted
        - the run terminates with 'done' (after exhausting retries the final
          error event uses MAX_RETRIES+1 budget)
        """
        valence_tool_end = {
            "event": "on_tool_end",
            "name": "validate_smiles",
            "metadata": {},
            "data": {
                "output": json.dumps(
                    {"error": "Explicit valence for atom # 0 C, 5, is greater than permitted"}
                )
            },
        }

        call_count = 0

        async def _fake_astream(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            # Always yield the same bad event to exhaust all retries quickly.
            yield valence_tool_end

        snapshot = MagicMock()
        snapshot.interrupts = []
        snapshot.config = {"configurable": {"checkpoint_id": "chk-abc"}}

        mock_graph = MagicMock()
        mock_graph.astream_events = _fake_astream
        mock_graph.aget_state = AsyncMock(return_value=snapshot)

        with (
            patch("app.agents.main_agent.engine.get_compiled_graph", return_value=mock_graph),
            patch("app.agents.main_agent.engine.has_persisted_session", new_callable=AsyncMock, return_value=False),
        ):
            events = await self._collect(
                engine, message="C(C)(C)(C)(C)C check this"
            )

        types = [e["type"] for e in events]
        # Self-correction thinking messages must appear
        thinking_events = [e for e in events if e["type"] == "thinking"]
        correction_msgs = [
            e for e in thinking_events if "自我修正" in e.get("text", "")
        ]
        assert len(correction_msgs) > 0, "Expected at least one self-correction thinking event"

        # After exhausting retries, an error event is emitted
        assert "error" in types

    async def test_cannot_resume_interrupt_without_persisted_state(
        self, engine: ChemSessionEngine
    ) -> None:
        with patch(
            "app.agents.main_agent.engine.has_persisted_session",
            new_callable=AsyncMock,
            return_value=False,
        ):
            events = await self._collect(
                engine,
                message="yes",
                interrupt_context={"interrupt_id": "intr-123"},
            )

        assert events[0]["type"] == "error"

    async def test_emits_plan_approval_request_from_pending_interrupt(
        self, engine: ChemSessionEngine
    ) -> None:
        snapshot = MagicMock()
        snapshot.interrupts = [
            MagicMock(
                id="intr-plan-001",
                value={
                    "type": "plan_approval_request",
                    "plan_id": "123e4567-e89b-12d3-a456-426614174000",
                    "plan_file_ref": "sess-test/123e4567-e89b-12d3-a456-426614174000.md",
                    "summary": "先验证 SMILES，再执行已批准步骤。",
                    "status": "pending_approval",
                    "mode": "plan",
                },
            )
        ]
        snapshot.config = {"configurable": {"checkpoint_id": "chk-plan"}}

        async def _fake_astream(*_args, **_kwargs):
            if False:
                yield {}

        mock_graph = MagicMock()
        mock_graph.astream_events = _fake_astream
        mock_graph.aget_state = AsyncMock(return_value=snapshot)

        with (
            patch("app.agents.main_agent.engine.get_compiled_graph", return_value=mock_graph),
            patch("app.agents.main_agent.engine.has_persisted_session", new_callable=AsyncMock, return_value=False),
        ):
            events = await self._collect(engine, message="为该分子先生成执行计划")

        plan_events = [e for e in events if e["type"] == "plan_approval_request"]
        assert len(plan_events) == 1
        assert plan_events[0]["plan_id"] == "123e4567-e89b-12d3-a456-426614174000"
        assert plan_events[0]["plan_file_ref"].endswith(".md")

    async def test_modify_plan_updates_file_without_resuming_graph(
        self, engine: ChemSessionEngine
    ) -> None:
        with (
            patch("app.agents.main_agent.engine.update_plan_file") as update_plan_file,
            patch("app.agents.main_agent.engine.get_compiled_graph") as get_graph,
        ):
            update_plan_file.return_value = MagicMock(
                plan_id="123e4567-e89b-12d3-a456-426614174000",
                plan_file_ref="sess-test/123e4567-e89b-12d3-a456-426614174000.md",
                summary="更新后的计划摘要",
                status="pending_approval",
            )
            events = await self._collect_resume(
                engine,
                action="modify",
                args={"content": "# Updated Plan\n1. Validate\n2. Execute"},
                plan_id="123e4567-e89b-12d3-a456-426614174000",
            )

        get_graph.assert_not_called()
        update_plan_file.assert_called_once()
        assert events[0]["type"] == "plan_modified"
        assert events[0]["plan_id"] == "123e4567-e89b-12d3-a456-426614174000"
        assert events[-1]["type"] == "done"

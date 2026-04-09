from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, patch
from typing import cast

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agents.nodes.executor import (
    _collect_recent_artifact_ids,
    _sanitize_message_bus_payload,
    tools_executor_node,
)
from app.agents.nodes.agent import chem_agent_node
from app.agents.state import ChemState
from app.agents.utils import normalize_messages_for_api, sanitize_message_for_state


def test_collect_recent_artifact_ids_returns_deduplicated_recent_list() -> None:
    artifacts = [
        {"artifact_id": "art_a"},
        {"artifact_id": "art_b"},
        {"artifact_id": "art_a"},
        {"artifact_id": "art_c"},
    ]

    assert _collect_recent_artifact_ids(artifacts, limit=3) == ["art_b", "art_a", "art_c"]


def test_sanitize_message_bus_payload_strips_binary_fields() -> None:
    parsed = {
        "artifact_id": "art_1",
        "pdbqt_content": "ATOM....",
        "sdf_content": "M  END",
        "smiles": "CCO",
    }

    cleaned = _sanitize_message_bus_payload("tool_prepare_pdbqt", parsed)
    assert cleaned is not None
    assert "pdbqt_content" not in cleaned
    assert "sdf_content" not in cleaned
    assert cleaned["artifact_payloads_removed"] == ["pdbqt_content", "sdf_content"]


def test_sanitize_message_bus_payload_strips_nested_binary_fields() -> None:
    parsed = {
        "type": "similarity",
        "molecule_1": {
            "smiles": "CCO",
            "image": "base64-a",
        },
        "comparisons": [
            {"score": 0.1, "highlighted_image": "base64-b"},
        ],
    }

    cleaned = _sanitize_message_bus_payload("tool_compute_similarity", parsed)
    assert cleaned is not None
    assert "image" not in cleaned["molecule_1"]
    assert "highlighted_image" not in cleaned["comparisons"][0]
    assert cleaned["artifact_payloads_removed"] == [
        "comparisons[0].highlighted_image",
        "molecule_1.image",
    ]


@pytest.mark.asyncio
async def test_summary_tool_message_is_compacted_without_artifact_redaction() -> None:
    message = ToolMessage(
        content=json.dumps(
            {
                "type": "evaluation",
                "is_valid": True,
                "artifact_id": "art_eval_1",
                "parent_artifact_id": None,
                "from_artifact": False,
                "validation": {
                    "is_valid": True,
                    "canonical_smiles": "CC(C)C[C@H](N)C(=O)O",
                    "formula": "C6H13NO2",
                    "molecular_weight": 131.17,
                },
                "descriptors": {
                    "molecular_weight": 131.17,
                    "logp": -1.52,
                    "tpsa": 63.32,
                    "qed": 0.71,
                    "sa_score": 2.4,
                    "fraction_csp3": 0.83,
                    "ring_count": 0,
                    "extra_blob": "X" * 1600,
                },
                "lipinski": {
                    "mw": 131.17,
                    "logp": -1.52,
                    "hbd": 2,
                    "hba": 2,
                    "violations": 0,
                    "passes": True,
                },
                "formula": "C6H13NO2",
                "smiles": "CC(C)C[C@H](N)C(=O)O",
                "name": "L-Leucine",
            },
            ensure_ascii=False,
        ),
        tool_call_id="call-eval",
        name="tool_evaluate_molecule",
    )

    with patch("app.agents.utils.store_engine_artifact", new=AsyncMock()) as store_mock:
        sanitized = await sanitize_message_for_state(message, source="tools_executor[0]")

    compact = json.loads(cast(str, sanitized.content))
    assert compact["content_compacted"] is True
    assert compact["artifact_id"] == "art_eval_1"
    assert compact["source_tool"] == "tool_evaluate_molecule"
    assert len(sanitized.content) < len(message.content)
    assert "temp_art_" not in sanitized.content
    store_mock.assert_not_awaited()


def test_normalize_messages_aggregates_omitted_tool_placeholders_across_rounds() -> None:
    messages = [
        AIMessage(
            content="first tool batch",
            tool_calls=[{"id": "call-1", "name": "tool_a", "args": {}}],
        ),
        ToolMessage(content="first result", tool_call_id="call-1", name="tool_a"),
        AIMessage(
            content="second tool batch",
            tool_calls=[{"id": "call-2", "name": "tool_b", "args": {}}],
        ),
        ToolMessage(content="second result", tool_call_id="call-2", name="tool_b"),
        AIMessage(
            content="third tool batch",
            tool_calls=[{"id": "call-3", "name": "tool_c", "args": {}}],
        ),
        ToolMessage(content="third result", tool_call_id="call-3", name="tool_c"),
    ]

    normalized = normalize_messages_for_api(messages, max_tool_history=1)
    omitted_messages = [
        msg for msg in normalized if isinstance(msg, ToolMessage) and "omitted" in str(msg.content).lower()
    ]

    assert len(omitted_messages) == 2
    assert str(omitted_messages[0].content).startswith("[System] 2 earlier tool results omitted")
    assert str(omitted_messages[1].content) == "[Omitted]"


@pytest.mark.asyncio
async def test_ask_human_interrupt_includes_active_artifact_context() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Need clarification",
                tool_calls=[
                    {
                        "name": "tool_ask_human",
                        "id": "call-1",
                        "args": {"question": "Which receptor should I use?", "options": ["MET", "EGFR"]},
                    }
                ],
            )
        ],
        "active_smiles": "CCO",
        "artifacts": [{"artifact_id": "art_receptor"}, {"artifact_id": "art_ligand"}],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
    })

    captured_payload: dict = {}

    def _fake_interrupt(payload: dict) -> dict:
        captured_payload.update(payload)
        return {"answer": "Use MET"}

    with patch("app.agents.nodes.executor.interrupt", side_effect=_fake_interrupt):
        result = await tools_executor_node(state, {"configurable": {}})

    assert captured_payload["known_smiles"] == "CCO"
    assert captured_payload["active_artifact_id"] == "art_ligand"
    assert captured_payload["recent_artifact_ids"] == ["art_receptor", "art_ligand"]
    tool_message = result["messages"][0]
    content = json.loads(tool_message.content)
    assert content["status"] == "clarification_received"


@pytest.mark.asyncio
async def test_run_sub_agent_receives_recent_artifact_ids_and_sanitized_response() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Delegate work",
                tool_calls=[
                    {
                        "name": "tool_run_sub_agent",
                        "id": "call-sub",
                        "args": {"mode": "explore", "task": "Compare recent ligands"},
                    }
                ],
            )
        ],
        "active_smiles": "CCO",
        "artifacts": [{"artifact_id": "art_a"}, {"artifact_id": "art_b"}],
        "molecule_workspace": [
            {
                "key": "smiles:CCO",
                "primary_name": "乙醇",
                "canonical_smiles": "CCO",
                "formula": "C2H6O",
            }
        ],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
    })

    captured_config: dict = {}

    class _FakeTool:
        name = "tool_run_sub_agent"

        async def ainvoke(self, args: dict, config: dict | None = None):
            captured_config.update(config or {})
            return json.dumps(
                {
                    "status": "ok",
                    "mode": "explore",
                    "sub_thread_id": "sub_123",
                    "execution_task_id": "exec_123",
                    "task_kind": "compare_scaffolds",
                    "output_contract": "json_findings",
                    "smiles_policy": "forbid_new",
                    "summary": "Finished comparison",
                    "completion": {
                        "summary": "Finished comparison",
                        "produced_artifact_ids": ["art_child"],
                        "metrics": {"shared_motif": "N-rich hinge binder"},
                        "advisory_active_smiles": "CCN",
                    },
                    "policy_conflicts": [],
                    "needs_followup": False,
                    "produced_artifacts": [
                        {
                            "artifact_id": "art_child",
                            "smiles": "CCN",
                            "pdbqt_content": "ATOM...",
                        }
                    ],
                    "suggested_active_smiles": "CCN",
                },
                ensure_ascii=False,
            )

    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_run_sub_agent": _FakeTool()}):
        result = await tools_executor_node(state, {"configurable": {"thread_id": "root"}})

    configurable = captured_config["configurable"]
    assert configurable["parent_active_artifact_id"] == "art_b"
    assert configurable["parent_artifact_ids"] == ["art_a", "art_b"]
    assert "乙醇" in configurable["parent_molecule_workspace_summary"]
    assert result["active_smiles"] == "CCN"
    assert result["artifacts"][0]["artifact_id"] == "art_child"
    assert result["molecule_workspace"][0]["canonical_smiles"] == "CCO"
    tool_message = result["messages"][0]
    content = json.loads(tool_message.content)
    assert content["status"] == "ok"
    assert content["task_kind"] == "compare_scaffolds"
    assert content["completion"]["metrics"]["shared_motif"] == "N-rich hinge binder"
    assert content["parent_decision"] is None
    assert content["artifact_payloads_removed"] == ["produced_artifacts[0].pdbqt_content"]


@pytest.mark.asyncio
async def test_failed_sub_agent_with_spawn_retries_in_new_execution_context() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Delegate failing work",
                tool_calls=[
                    {
                        "name": "tool_run_sub_agent",
                        "id": "call-sub-fail",
                        "args": {"mode": "general", "task": "Attempt execution"},
                    }
                ],
            )
        ],
        "active_smiles": "CCO",
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
        "active_subtasks": {},
        "active_subtask_id": None,
        "sub_agent_result": None,
        "subtask_control": None,
    })

    seen_configs: list[dict] = []

    class _FailThenRecoverTool:
        name = "tool_run_sub_agent"

        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, args: dict, config: dict | None = None):
            self.calls += 1
            seen_configs.append(dict(config or {}))
            if self.calls == 1:
                return json.dumps(
                    {
                        "status": "failed",
                        "mode": "general",
                        "sub_thread_id": "exec_old",
                        "execution_task_id": "exec_old",
                        "summary": "Bad route",
                        "failure": {
                            "status": "failed",
                            "summary": "Bad route",
                            "error": "validation failed 3 times",
                            "failure_category": "validation",
                            "failed_tool_name": "tool_validate_smiles",
                            "failed_args_signature": "abc123",
                            "is_recoverable": False,
                            "recommended_action": "spawn",
                        },
                        "needs_followup": True,
                    },
                    ensure_ascii=False,
                )

            return json.dumps(
                {
                    "status": "ok",
                    "mode": "general",
                    "sub_thread_id": "exec_new",
                    "execution_task_id": str(((config or {}).get("configurable") or {}).get("execution_task_id") or ""),
                    "summary": "Recovered in fresh worker",
                    "completion": {
                        "summary": "Recovered in fresh worker",
                        "produced_artifact_ids": [],
                        "metrics": {},
                        "advisory_active_smiles": "",
                    },
                    "needs_followup": False,
                },
                ensure_ascii=False,
            )

    fake_tool = _FailThenRecoverTool()
    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_run_sub_agent": fake_tool}):
        result = await tools_executor_node(state, {"configurable": {"thread_id": "root"}})

    assert fake_tool.calls == 2
    first_execution_id = str((seen_configs[0].get("configurable") or {}).get("execution_task_id") or "")
    second_execution_id = str((seen_configs[1].get("configurable") or {}).get("execution_task_id") or "")
    assert first_execution_id != second_execution_id
    content = json.loads(result["messages"][0].content)
    assert content["status"] == "ok"
    assert content["parent_decision"] == "spawn"


@pytest.mark.asyncio
async def test_failed_sub_agent_with_continue_retries_same_execution_context() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Delegate retryable work",
                tool_calls=[
                    {
                        "name": "tool_run_sub_agent",
                        "id": "call-sub-continue",
                        "args": {"mode": "general", "task": "Attempt execution", "delegation": {"inline_context": "base"}},
                    }
                ],
            )
        ],
        "active_smiles": "CCO",
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
        "active_subtasks": {},
        "active_subtask_id": None,
        "sub_agent_result": None,
        "subtask_control": None,
    })

    seen_args: list[dict] = []
    seen_configs: list[dict] = []

    class _RetrySameTaskTool:
        name = "tool_run_sub_agent"

        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, args: dict, config: dict | None = None):
            self.calls += 1
            seen_args.append(dict(args))
            seen_configs.append(dict(config or {}))
            if self.calls == 1:
                return json.dumps(
                    {
                        "status": "failed",
                        "mode": "general",
                        "sub_thread_id": "exec_same",
                        "execution_task_id": "exec_same",
                        "summary": "Transient issue",
                        "failure": {
                            "status": "failed",
                            "summary": "Transient issue",
                            "error": "connection reset by peer",
                            "failure_category": "infrastructure",
                            "failed_tool_name": "tool_web_search",
                            "failed_args_signature": "sig1",
                            "is_recoverable": True,
                            "recommended_action": "continue",
                        },
                        "needs_followup": True,
                    },
                    ensure_ascii=False,
                )

            return json.dumps(
                {
                    "status": "ok",
                    "mode": "general",
                    "sub_thread_id": "exec_same",
                    "execution_task_id": "exec_same",
                    "summary": "Recovered in same worker",
                    "completion": {
                        "summary": "Recovered in same worker",
                        "produced_artifact_ids": [],
                        "metrics": {},
                        "advisory_active_smiles": "",
                    },
                    "needs_followup": False,
                },
                ensure_ascii=False,
            )

    fake_tool = _RetrySameTaskTool()
    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_run_sub_agent": fake_tool}):
        result = await tools_executor_node(state, {"configurable": {"thread_id": "root", "execution_task_id": "exec_same"}})

    assert fake_tool.calls == 2
    first_execution_id = str((seen_configs[0].get("configurable") or {}).get("execution_task_id") or "")
    second_execution_id = str((seen_configs[1].get("configurable") or {}).get("execution_task_id") or "")
    assert first_execution_id == second_execution_id
    retry_inline_context = str(((seen_args[1].get("delegation") or {}).get("inline_context") or ""))
    assert "Continue same worker" in retry_inline_context
    content = json.loads(result["messages"][0].content)
    assert content["status"] == "ok"
    assert content["parent_decision"] == "continue"


@pytest.mark.asyncio
async def test_tools_executor_redacts_large_biostructure_messages_to_temp_artifact(caplog: pytest.LogCaptureFixture) -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Run bulky tool",
                tool_calls=[
                    {
                        "name": "tool_bulk_structure",
                        "id": "call-bulk",
                        "args": {},
                    }
                ],
            )
        ],
        "active_smiles": None,
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
    })

    huge_pdb = "HEADER    PROTEIN\n" + ("ATOM      1  C   LIG A   1      10.000  10.000  10.000\n" * 2000)

    class _FakeTool:
        name = "tool_bulk_structure"

        async def ainvoke(self, args: dict, config: dict | None = None):
            return huge_pdb

    caplog.set_level(logging.WARNING)

    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_bulk_structure": _FakeTool()}), \
         patch("app.agents.utils.store_engine_artifact", new_callable=AsyncMock) as store_mock:
        result = await tools_executor_node(state, {"configurable": {}})

    tool_message = result["messages"][0]
    assert len(str(tool_message.content)) < 1000
    assert "Data Redacted due to size" in str(tool_message.content)
    artifact_id = str(tool_message.content).split("Artifact ID: ", 1)[1].rstrip("]")
    assert artifact_id.startswith("temp_art_")
    store_mock.assert_awaited_once_with(artifact_id, huge_pdb, tier="temp")
    assert artifact_id in caplog.text
    assert "Context firewall redacted message before state write" in caplog.text


@pytest.mark.asyncio
async def test_chem_agent_redacts_large_model_message_before_state_write() -> None:
    state = cast(ChemState, {
        "messages": [AIMessage(content="prior turn")],
        "active_smiles": None,
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
    })

    huge_response = "HEADER    PROTEIN\n" + ("ATOM      1  C   LIG A   1      10.000  10.000  10.000\n" * 1000)

    class _FakeBoundLlm:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, prompt_messages):
            return AIMessage(content=huge_response)

    with patch("app.agents.nodes.agent.build_llm", return_value=_FakeBoundLlm()), \
         patch("app.agents.utils.store_engine_artifact", new_callable=AsyncMock) as store_mock:
        result = await chem_agent_node(state)

    ai_message = result["messages"][0]
    assert len(str(ai_message.content)) < 1000
    assert "Data Redacted due to size" in str(ai_message.content)
    artifact_id = str(ai_message.content).split("Artifact ID: ", 1)[1].rstrip("]")
    store_mock.assert_awaited_once_with(artifact_id, huge_response, tier="temp")


@pytest.mark.asyncio
async def test_chem_agent_preserves_long_natural_language_report_in_state() -> None:
    state = cast(ChemState, {
        "messages": [AIMessage(content="prior turn")],
        "active_smiles": None,
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
    })

    report = "".join([f"Section {index}: this is a detailed analysis paragraph.\n" for index in range(160)])

    class _FakeBoundLlm:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, prompt_messages):
            return AIMessage(content=report)

    with patch("app.agents.nodes.agent.build_llm", return_value=_FakeBoundLlm()), \
         patch("app.agents.utils.store_engine_artifact", new_callable=AsyncMock) as store_mock:
        result = await chem_agent_node(state)

    ai_message = result["messages"][0]
    assert ai_message.content == report
    store_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_sanitize_ai_tool_call_args_redacts_large_raw_chemistry_inputs() -> None:
    huge_sdf = "HEADER    PROTEIN\n" + ("ATOM      1  C   LIG A   1      10.000  10.000  10.000\n" * 200)
    message = AIMessage(
        content="Convert this structure",
        tool_calls=[
            {
                "name": "tool_convert_format",
                "id": "call-convert",
                "args": {"molecule_str": huge_sdf, "input_fmt": "sdf", "output_fmt": "pdb"},
            }
        ],
    )

    with patch("app.agents.utils.store_engine_artifact", new_callable=AsyncMock) as store_mock:
        sanitized = await sanitize_message_for_state(message, source="chem_agent")

    sanitized_ai = cast(AIMessage, sanitized)
    assert sanitized_ai.tool_calls[0]["args"]["__redacted__"] is True
    artifact_id = sanitized_ai.tool_calls[0]["args"]["__artifact_id__"]
    assert artifact_id.startswith("temp_art_")
    store_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_tools_executor_restores_redacted_tool_call_args_from_artifact() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Run conversion",
                tool_calls=[
                    {
                        "name": "tool_convert_format",
                        "id": "call-convert",
                        "args": {
                            "__artifact_id__": "temp_art_args",
                            "__redacted__": True,
                            "message": "[Tool args redacted]",
                        },
                    }
                ],
            )
        ],
        "active_smiles": None,
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
    })

    captured_args: dict = {}

    class _FakeTool:
        name = "tool_convert_format"

        async def ainvoke(self, args: dict, config: dict | None = None):
            captured_args.update(args)
            return json.dumps({"status": "ok", "output_format": "pdb", "result": "done"}, ensure_ascii=False)

    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_convert_format": _FakeTool()}), \
         patch("app.agents.nodes.executor.get_engine_artifact", new=AsyncMock(return_value={"molecule_str": "C", "input_fmt": "smi", "output_fmt": "pdb"})):
        result = await tools_executor_node(state, {"configurable": {}})

    assert captured_args == {"molecule_str": "C", "input_fmt": "smi", "output_fmt": "pdb"}
    content = json.loads(result["messages"][0].content)
    assert content["status"] == "ok"


@pytest.mark.asyncio
async def test_update_task_status_persists_summary_on_completion() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Complete task",
                tool_calls=[
                    {
                        "name": "tool_update_task_status",
                        "id": "call-task-complete",
                        "args": {
                            "task_id": "1",
                            "status": "completed",
                            "summary": "已提炼出双芳环+酰胺氢键锚点。",
                        },
                    }
                ],
            )
        ],
        "active_smiles": "CCO",
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [{"id": "1", "description": "提炼药效团", "status": "in_progress"}],
        "is_complex": True,
        "evidence_revision": 4,
    })

    with patch("app.agents.nodes.executor.dispatch_task_update", new=AsyncMock()):
        result = await tools_executor_node(state, {"configurable": {}})

    assert result["tasks"][0]["status"] == "completed"
    assert result["tasks"][0]["summary"] == "已提炼出双芳环+酰胺氢键锚点。"
    assert result["tasks"][0]["completion_revision"] == 4
    content = json.loads(result["messages"][0].content)
    assert content["summary"] == "已提炼出双芳环+酰胺氢键锚点。"


@pytest.mark.asyncio
async def test_update_task_status_accepts_prefixed_task_label() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Complete task with prefixed id",
                tool_calls=[
                    {
                        "name": "tool_update_task_status",
                        "id": "call-task-prefixed",
                        "args": {
                            "task_id": "1. 解析SMILES",
                            "status": "completed",
                            "summary": "已解析 L-Leucine 的 SMILES。",
                        },
                    }
                ],
            )
        ],
        "active_smiles": "CCO",
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [{"id": "1", "description": "解析SMILES", "status": "in_progress"}],
        "is_complex": True,
        "evidence_revision": 2,
    })

    with patch("app.agents.nodes.executor.dispatch_task_update", new=AsyncMock()):
        result = await tools_executor_node(state, {"configurable": {}})

    assert result["tasks"][0]["status"] == "completed"
    content = json.loads(result["messages"][0].content)
    assert content["status"] == "success"
    assert content["task_id"] == "1"
    assert content["summary"] == "已解析 L-Leucine 的 SMILES。"


@pytest.mark.asyncio
async def test_completed_task_cannot_reopen_without_new_evidence() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Reopen task",
                tool_calls=[
                    {
                        "name": "tool_update_task_status",
                        "id": "call-task-reopen",
                        "args": {"task_id": "1", "status": "in_progress"},
                    }
                ],
            )
        ],
        "active_smiles": "CCO",
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [
            {
                "id": "1",
                "description": "提炼药效团",
                "status": "completed",
                "summary": "已锁定双芳环锚点。",
                "completion_revision": 7,
            }
        ],
        "is_complex": True,
        "evidence_revision": 7,
    })

    dispatch_mock = AsyncMock()
    with patch("app.agents.nodes.executor.dispatch_task_update", new=dispatch_mock):
        result = await tools_executor_node(state, {"configurable": {}})

    assert result["tasks"][0]["status"] == "completed"
    assert result["tasks"][0]["summary"] == "已锁定双芳环锚点。"
    dispatch_mock.assert_not_awaited()
    content = json.loads(result["messages"][0].content)
    assert content["status"] == "ignored"
    assert content["reason"] == "task_already_completed_without_new_evidence"


@pytest.mark.asyncio
async def test_pubchem_lookup_updates_structured_molecule_workspace() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Lookup compound",
                tool_calls=[
                    {
                        "name": "tool_pubchem_lookup",
                        "id": "call-pubchem",
                        "args": {"name": "capmatinib"},
                    }
                ],
            )
        ],
        "active_smiles": None,
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
    })

    class _FakePubChemTool:
        name = "tool_pubchem_lookup"

        async def ainvoke(self, args: dict, config: dict | None = None):  # noqa: ARG002
            return json.dumps(
                {
                    "found": True,
                    "name": args["name"],
                    "canonical_smiles": "CC(C1=C(C=CC(=C1Cl)F)Cl)OC2=C(N=CC(=C2)C3=CN(N=C3)C4CCNCC4)N",
                    "isomeric_smiles": "CC(C1=C(C=CC(=C1Cl)F)Cl)OC2=C(N=CC(=C2)C3=CN(N=C3)C4CCNCC4)N",
                    "formula": "C23H17Cl2FN4O",
                    "molecular_weight": 477.31,
                    "iupac_name": "capmatinib",
                },
                ensure_ascii=False,
            )

    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_pubchem_lookup": _FakePubChemTool()}):
        result = await tools_executor_node(state, {"configurable": {}})

    assert result["active_smiles"] == "CC(C1=C(C=CC(=C1Cl)F)Cl)OC2=C(N=CC(=C2)C3=CN(N=C3)C4CCNCC4)N"
    assert result["molecule_workspace"][0]["primary_name"] == "capmatinib"
    assert result["molecule_workspace"][0]["formula"] == "C23H17Cl2FN4O"
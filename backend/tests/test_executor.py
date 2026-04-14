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
from app.domain.schemas.agent import ChemState
from app.agents.utils import normalize_messages_for_api, sanitize_message_for_state
from app.domain.schemas.workspace import WorkspaceProjection


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
async def test_summary_tool_message_passes_through_unchanged() -> None:
    content = json.dumps(
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
    )
    message = ToolMessage(
        content=content,
        tool_call_id="call-eval",
        name="tool_evaluate_molecule",
    )

    sanitized = await sanitize_message_for_state(message, source="tools_executor[0]")

    assert sanitized.content == content


@pytest.mark.asyncio
async def test_sub_agent_tool_message_passes_through_unchanged() -> None:
    message = ToolMessage(
        content=json.dumps(
            {
                "status": "ok",
                "summary": "S" * 2000,
                "completion": {
                    "summary": "Sub-agent completed",
                    "produced_artifact_ids": ["art_a", "art_b"],
                },
                "produced_artifacts": [{"artifact_id": "art_a"}] * 20,
            },
            ensure_ascii=False,
        ),
        tool_call_id="call-subagent",
        name="tool_run_sub_agent",
    )

    sanitized = await sanitize_message_for_state(message, source="tools_executor[0]")

    assert sanitized.content == message.content


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
    captured_args: dict = {}

    class _FakeTool:
        name = "tool_run_sub_agent"

        async def ainvoke(self, args: dict, config: dict | None = None):
            captured_args.update(args)
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
    assert captured_args["artifact_ids"] == ["art_a", "art_b"]
    assert captured_args["delegation"]["artifact_pointers"] == ["art_a", "art_b"]
    assert captured_args["delegation"]["active_artifact_id"] == "art_b"
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
async def test_run_sub_agent_preserves_explicit_artifact_ids_over_parent_fallback() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Delegate work",
                tool_calls=[
                    {
                        "name": "tool_run_sub_agent",
                        "id": "call-sub-explicit",
                        "args": {
                            "mode": "explore",
                            "task": "Use explicit artifact only",
                            "artifact_ids": ["art_explicit"],
                            "delegation": {"artifact_pointers": ["art_explicit"]},
                        },
                    }
                ],
            )
        ],
        "active_smiles": "CCO",
        "artifacts": [{"artifact_id": "art_parent_a"}, {"artifact_id": "art_parent_b"}],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
    })

    captured_args: dict = {}

    class _FakeTool:
        name = "tool_run_sub_agent"

        async def ainvoke(self, args: dict, config: dict | None = None):  # noqa: ARG002
            captured_args.update(args)
            return json.dumps({"status": "ok", "summary": "done", "completion": {"summary": "done"}}, ensure_ascii=False)

    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_run_sub_agent": _FakeTool()}):
        await tools_executor_node(state, {"configurable": {"thread_id": "root"}})

    assert captured_args["artifact_ids"] == ["art_explicit"]
    assert captured_args["delegation"]["artifact_pointers"] == ["art_explicit"]


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
async def test_tools_executor_passes_large_tool_result_through(caplog: pytest.LogCaptureFixture) -> None:
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

    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_bulk_structure": _FakeTool()}):
        result = await tools_executor_node(state, {"configurable": {}})

    tool_message = result["messages"][0]
    assert "Data Redacted" not in str(tool_message.content)
    assert "Context firewall" not in caplog.text


@pytest.mark.asyncio
async def test_chem_agent_passes_large_model_message_through() -> None:
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

    with patch("app.agents.nodes.agent.build_llm", return_value=_FakeBoundLlm()):
        result = await chem_agent_node(state)

    ai_message = result["messages"][0]
    assert ai_message.content == huge_response


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

    with patch("app.agents.nodes.agent.build_llm", return_value=_FakeBoundLlm()):
        result = await chem_agent_node(state)

    ai_message = result["messages"][0]
    assert ai_message.content == report


@pytest.mark.asyncio
async def test_chem_agent_drains_pending_worker_tasks_into_workspace_updates() -> None:
    state = cast(ChemState, {
        "messages": [AIMessage(content="prior turn")],
        "active_smiles": "CCO",
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
        "workspace_projection": {
            "project_id": "project-async",
            "workspace_id": "ws_async",
            "version": 1,
            "nodes": {
                "mol_root": {
                    "node_id": "mol_root",
                    "handle": "root_molecule",
                    "canonical_smiles": "CCO",
                    "display_name": "ethanol",
                    "parent_node_id": None,
                    "origin": "root_commit",
                    "status": "active",
                    "diagnostics": {},
                    "artifact_ids": [],
                    "hover_text": "",
                }
            },
            "relations": {},
            "handle_bindings": {
                "root_molecule": {
                    "handle": "root_molecule",
                    "node_id": "mol_root",
                    "bound_at_version": 1,
                }
            },
            "viewport": {"focused_handles": ["root_molecule"], "reference_handle": "root_molecule"},
            "rules": [],
            "async_jobs": {
                "job_call-conf-1": {
                    "job_id": "job_call-conf-1",
                    "job_type": "tool_build_3d_conformer",
                    "target_handle": "root_molecule",
                    "target_node_id": "mol_root",
                    "base_workspace_version": 1,
                    "status": "running",
                    "stale_reason": "",
                    "artifact_id": None,
                    "result_summary": "",
                }
            },
        },
        "pending_worker_tasks": [
            {
                "task_id": "task_conf_1",
                "task_name": "babel.build_3d_conformer",
                "tool_name": "tool_build_3d_conformer",
                "workspace_job_id": "job_call-conf-1",
                "workspace_target_handle": "root_molecule",
                "project_id": "project-async",
                "workspace_id": "ws_async",
                "workspace_version": 1,
            }
        ],
    })

    class _FakeBoundLlm:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, prompt_messages):
            assert any(getattr(msg, "type", "") == "tool" for msg in prompt_messages)
            return AIMessage(content="Background result acknowledged")

    async def _fake_drain_pending_worker_tasks(state: ChemState, config: dict):  # noqa: ARG001
        return {
            "messages": [ToolMessage(content=json.dumps({"status": "success"}, ensure_ascii=False), tool_call_id="task_conf_1", name="tool_build_3d_conformer")],
            "artifacts": [{"kind": "conformer_sdf", "artifact_id": "art_conf_1", "smiles": "CCO"}],
            "workspace_events": [{"type": "job.completed", "job_id": "job_call-conf-1", "status": "completed"}],
            "workspace_projection": {
                "project_id": "project-async",
                "workspace_id": "ws_async",
                "version": 2,
                "nodes": {
                    "mol_root": {
                        "node_id": "mol_root",
                        "handle": "root_molecule",
                        "canonical_smiles": "CCO",
                        "display_name": "ethanol",
                        "parent_node_id": None,
                        "origin": "root_commit",
                        "status": "active",
                        "diagnostics": {"conformer_status": "ready", "energy_kcal_mol": -7.2},
                        "artifact_ids": ["art_conf_1"],
                        "hover_text": "3D构象已生成，SDF 文件已发送给用户",
                    }
                },
                "relations": {},
                "handle_bindings": {
                    "root_molecule": {"handle": "root_molecule", "node_id": "mol_root", "bound_at_version": 1}
                },
                "viewport": {"focused_handles": ["root_molecule"], "reference_handle": "root_molecule"},
                "rules": [],
                "async_jobs": {
                    "job_call-conf-1": {
                        "job_id": "job_call-conf-1",
                        "job_type": "tool_build_3d_conformer",
                        "target_handle": "root_molecule",
                        "target_node_id": "mol_root",
                        "base_workspace_version": 1,
                        "status": "completed",
                        "stale_reason": "",
                        "artifact_id": "art_conf_1",
                        "result_summary": "3D构象已生成，SDF 文件已发送给用户",
                    }
                },
            },
            "pending_worker_tasks": [],
            "tool_events": [],
        }

    with patch("app.agents.nodes.agent.build_llm", return_value=_FakeBoundLlm()), \
         patch("app.agents.nodes.agent.drain_pending_worker_tasks", new=_fake_drain_pending_worker_tasks), \
         patch("app.agents.postprocessors.adispatch_custom_event", new=AsyncMock()):
        result = await chem_agent_node(state, {"configurable": {"thread_id": "project-async"}})

    assert result["pending_worker_tasks"] == []
    assert any(event["type"] == "job.completed" for event in result["workspace_events"])
    assert len(result["messages"]) == 2
    assert result["artifacts"]


@pytest.mark.asyncio
async def test_sanitize_ai_tool_call_args_passes_through_unchanged() -> None:
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

    sanitized = await sanitize_message_for_state(message, source="chem_agent")

    sanitized_ai = cast(AIMessage, sanitized)
    assert sanitized_ai.tool_calls[0]["args"] == {"molecule_str": huge_sdf, "input_fmt": "sdf", "output_fmt": "pdb"}


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


@pytest.mark.asyncio
async def test_node_create_protocol_updates_workspace_projection_and_events() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Create root node",
                tool_calls=[
                    {
                        "name": "tool_create_molecule_node",
                        "id": "call-root-node",
                        "args": {"smiles": "CCO"},
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

    class _FakeStateTool:
        name = "tool_create_molecule_node"

        async def ainvoke(self, args: dict, config: dict | None = None):  # noqa: ARG002
            return json.dumps(
                {
                    "__chem_protocol__": "NodeCreate",
                    "artifact_id": "mol_root",
                    "smiles": args["smiles"],
                    "status": "staged",
                    "aliases": ["Ibrutinib"],
                },
                ensure_ascii=False,
            )

    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_create_molecule_node": _FakeStateTool()}):
        result = await tools_executor_node(state, {"configurable": {"thread_id": "project-alpha"}})

    workspace = result["workspace_projection"]
    assert isinstance(workspace, WorkspaceProjection)
    assert workspace.viewport.reference_handle == "root_molecule"
    assert workspace.viewport.focused_handles == ["root_molecule"]
    assert workspace.handle_bindings["root_molecule"].node_id == "mol_root"
    assert any(event["type"] == "molecule.upserted" for event in result["workspace_events"])
    assert any(event["type"] == "workspace.delta" for event in result["workspace_events"])


@pytest.mark.asyncio
async def test_invalid_parent_protocol_is_rejected_in_workspace_projection() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Create invalid child node",
                tool_calls=[
                    {
                        "name": "tool_create_molecule_node",
                        "id": "call-invalid-child",
                        "args": {"smiles": "CCN"},
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

    class _FakeStateTool:
        name = "tool_create_molecule_node"

        async def ainvoke(self, args: dict, config: dict | None = None):  # noqa: ARG002
            return json.dumps(
                {
                    "__chem_protocol__": "NodeCreate",
                    "artifact_id": "mol_child",
                    "smiles": args["smiles"],
                    "parent_id": "mol_missing_parent",
                    "status": "staged",
                },
                ensure_ascii=False,
            )

    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_create_molecule_node": _FakeStateTool()}):
        result = await tools_executor_node(state, {"configurable": {"thread_id": "project-beta"}})

    workspace = result["workspace_projection"]
    assert isinstance(workspace, WorkspaceProjection)
    assert workspace.nodes == {}
    assert any(event["type"] == "workspace.delta" and event.get("status") == "rejected" for event in result["workspace_events"])


@pytest.mark.asyncio
async def test_workspace_mutation_protocol_batches_graph_and_viewport_updates() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Commit batched workspace mutation",
                tool_calls=[
                    {
                        "name": "tool_commit_molecule_mutation",
                        "id": "call-workspace-mutation",
                        "args": {"operations": []},
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

    class _FakeMutationTool:
        name = "tool_commit_molecule_mutation"

        async def ainvoke(self, args: dict, config: dict | None = None):  # noqa: ARG002
            return json.dumps(
                {
                    "__chem_protocol__": "WorkspaceMutation",
                    "operations": [
                        {
                            "action": "upsert_root",
                            "artifact_id": "mol_root",
                            "smiles": "CCO",
                            "display_name": "Seed",
                            "status": "active",
                        },
                        {
                            "action": "upsert_candidate",
                            "artifact_id": "mol_child",
                            "smiles": "CCN",
                            "parent_id": "mol_root",
                            "display_name": "Child",
                            "creation_operation": "scaffold_hop",
                        },
                        {
                            "action": "set_viewport",
                            "focused_artifact_ids": ["mol_root", "mol_child"],
                            "reference_artifact_id": "mol_root",
                        },
                    ],
                },
                ensure_ascii=False,
            )

    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_commit_molecule_mutation": _FakeMutationTool()}):
        result = await tools_executor_node(state, {"configurable": {"thread_id": "project-gamma"}})

    workspace = result["workspace_projection"]
    assert isinstance(workspace, WorkspaceProjection)
    assert workspace.viewport.focused_handles == ["root_molecule", "candidate_1"]
    assert workspace.viewport.reference_handle == "root_molecule"
    assert workspace.handle_bindings["root_molecule"].node_id == "mol_root"
    assert workspace.handle_bindings["candidate_1"].node_id == "mol_child"
    assert any(event["type"] == "molecule.upserted" for event in result["workspace_events"])
    assert any(event["type"] == "relation.upserted" for event in result["workspace_events"])
    assert any(event["type"] == "viewport.changed" for event in result["workspace_events"])
    assert any(event["type"] == "workspace.delta" and event.get("scope") == "workspace" for event in result["workspace_events"])


@pytest.mark.asyncio
async def test_build_3d_conformer_emits_job_lifecycle_and_updates_workspace_projection() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Generate 3D conformer",
                tool_calls=[
                    {
                        "name": "tool_build_3d_conformer",
                        "id": "call-conf-1",
                        "args": {"smiles": "CCO", "name": "ethanol"},
                    }
                ],
            )
        ],
        "active_smiles": "CCO",
        "artifacts": [{"artifact_id": "art_existing"}],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
        "workspace_projection": {
            "project_id": "project-async",
            "workspace_id": "ws_async",
            "version": 1,
            "nodes": {
                "mol_root": {
                    "node_id": "mol_root",
                    "handle": "root_molecule",
                    "canonical_smiles": "CCO",
                    "display_name": "ethanol",
                    "parent_node_id": None,
                    "origin": "root_commit",
                    "status": "active",
                    "diagnostics": {},
                    "artifact_ids": [],
                    "hover_text": "",
                }
            },
            "relations": {},
            "handle_bindings": {
                "root_molecule": {
                    "handle": "root_molecule",
                    "node_id": "mol_root",
                    "bound_at_version": 1,
                }
            },
            "viewport": {"focused_handles": ["root_molecule"], "reference_handle": "root_molecule"},
            "rules": [],
            "async_jobs": {},
        },
    })

    with patch(
        "app.agents.nodes.executor.submit_async_tool_task",
        new=AsyncMock(
            return_value={
                "is_valid": True,
                "smiles": "CCO",
                "name": "ethanol",
                "energy_kcal_mol": -7.2,
                "message": "3D构象已生成，SDF 文件已发送给用户",
            }
        ),
    ), patch("app.agents.postprocessors.adispatch_custom_event", new=AsyncMock()):
        result = await tools_executor_node(state, {"configurable": {"thread_id": "project-async"}})

    workspace = result["workspace_projection"]
    root_node = workspace.nodes[workspace.handle_bindings["root_molecule"].node_id]
    assert any(event["type"] == "job.started" for event in result["workspace_events"])
    assert any(event["type"] == "job.completed" for event in result["workspace_events"])
    assert root_node.diagnostics["conformer_status"] == "ready"
    assert root_node.diagnostics["energy_kcal_mol"] == -7.2


@pytest.mark.asyncio
async def test_prepare_pdbqt_emits_job_lifecycle_and_updates_workspace_projection() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Prepare PDBQT",
                tool_calls=[
                    {
                        "name": "tool_prepare_pdbqt",
                        "id": "call-pdbqt-1",
                        "args": {"smiles": "CCO", "name": "ethanol"},
                    }
                ],
            )
        ],
        "active_smiles": "CCO",
        "artifacts": [{"artifact_id": "art_existing"}],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
        "workspace_projection": {
            "project_id": "project-async",
            "workspace_id": "ws_async",
            "version": 1,
            "nodes": {
                "mol_root": {
                    "node_id": "mol_root",
                    "handle": "root_molecule",
                    "canonical_smiles": "CCO",
                    "display_name": "ethanol",
                    "parent_node_id": None,
                    "origin": "root_commit",
                    "status": "active",
                    "diagnostics": {},
                    "artifact_ids": [],
                    "hover_text": "",
                }
            },
            "relations": {},
            "handle_bindings": {
                "root_molecule": {
                    "handle": "root_molecule",
                    "node_id": "mol_root",
                    "bound_at_version": 1,
                }
            },
            "viewport": {"focused_handles": ["root_molecule"], "reference_handle": "root_molecule"},
            "rules": [],
            "async_jobs": {},
        },
    })

    with patch(
        "app.agents.nodes.executor.submit_async_tool_task",
        new=AsyncMock(
            return_value={
                "is_valid": True,
                "smiles": "CCO",
                "name": "ethanol",
                "rotatable_bonds": 2,
                "message": "PDBQT 文件已生成，结果已发送给用户",
            }
        ),
    ), patch("app.agents.postprocessors.adispatch_custom_event", new=AsyncMock()):
        result = await tools_executor_node(state, {"configurable": {"thread_id": "project-async"}})

    workspace = result["workspace_projection"]
    root_node = workspace.nodes[workspace.handle_bindings["root_molecule"].node_id]
    assert any(event["type"] == "job.started" for event in result["workspace_events"])
    assert any(event["type"] == "job.completed" for event in result["workspace_events"])
    assert root_node.diagnostics["pdbqt_status"] == "ready"
    assert root_node.diagnostics["rotatable_bonds"] == 2


@pytest.mark.asyncio
async def test_build_3d_conformer_queues_pending_worker_task_when_worker_submission_deferred() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Generate 3D conformer",
                tool_calls=[
                    {
                        "name": "tool_build_3d_conformer",
                        "id": "call-conf-queued",
                        "args": {"smiles": "CCO", "name": "ethanol"},
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
        "workspace_projection": {
            "project_id": "project-async",
            "workspace_id": "ws_async",
            "version": 1,
            "nodes": {
                "mol_root": {
                    "node_id": "mol_root",
                    "handle": "root_molecule",
                    "canonical_smiles": "CCO",
                    "display_name": "ethanol",
                    "parent_node_id": None,
                    "origin": "root_commit",
                    "status": "active",
                    "diagnostics": {},
                    "artifact_ids": [],
                    "hover_text": "",
                }
            },
            "relations": {},
            "handle_bindings": {
                "root_molecule": {
                    "handle": "root_molecule",
                    "node_id": "mol_root",
                    "bound_at_version": 1,
                }
            },
            "viewport": {"focused_handles": ["root_molecule"], "reference_handle": "root_molecule"},
            "rules": [],
            "async_jobs": {},
        },
    })

    with patch(
        "app.agents.nodes.executor.submit_async_tool_task",
        new=AsyncMock(
            return_value={
                "status": "queued",
                "is_valid": True,
                "message": "3D构象任务已提交，正在后台生成。",
                "task_id": "task_conf_queued",
                "task_name": "babel.build_3d_conformer",
                "__async_task__": {
                    "task_id": "task_conf_queued",
                    "task_name": "babel.build_3d_conformer",
                    "task_context": {
                        "project_id": "project-async",
                        "workspace_id": "ws_async",
                        "workspace_version": 2,
                    },
                },
            }
        ),
    ):
        result = await tools_executor_node(state, {"configurable": {"thread_id": "project-async"}})

    assert result["pending_worker_tasks"][0]["task_id"] == "task_conf_queued"
    assert any(event["type"] == "job.started" for event in result["workspace_events"])
    assert any(event["type"] == "job.progress" and event.get("status") == "queued" for event in result["workspace_events"])
    assert not any(event["type"] == "job.completed" for event in result["workspace_events"])


@pytest.mark.asyncio
async def test_murcko_scaffold_tool_result_passes_through() -> None:
    state = cast(ChemState, {
        "messages": [
            AIMessage(
                content="Extract scaffold",
                tool_calls=[
                    {
                        "name": "tool_murcko_scaffold",
                        "id": "call-murcko",
                        "args": {"smiles": "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O"},
                    }
                ],
            )
        ],
        "active_smiles": "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O",
        "artifacts": [],
        "molecule_workspace": [],
        "tasks": [],
        "is_complex": False,
        "evidence_revision": 0,
    })

    class _FakeMurckoTool:
        name = "tool_murcko_scaffold"

        async def ainvoke(self, args: dict, config: dict | None = None):  # noqa: ARG002
            return json.dumps(
                {
                    "type": "scaffold",
                    "is_valid": True,
                    "smiles": args["smiles"],
                    "scaffold_smiles": "c1ccccc1",
                    "generic_scaffold_smiles": "C1CCCCC1",
                    "molecule_image": "A" * 18000,
                    "scaffold_image": "B" * 12000,
                },
                ensure_ascii=False,
            )

    with patch.dict("app.agents.nodes.executor._TOOL_LOOKUP", {"tool_murcko_scaffold": _FakeMurckoTool()}), \
         patch("app.agents.postprocessors.adispatch_custom_event", new=AsyncMock()):
        result = await tools_executor_node(state, {"configurable": {}})

    content = json.loads(result["messages"][0].content)
    assert content["type"] == "scaffold"
    assert content["scaffold_smiles"] == "c1ccccc1"
    assert content["generic_scaffold_smiles"] == "C1CCCCC1"
    assert content["message"] == "Murcko scaffold 已提取，结构图已发送给用户"
    assert "molecule_image" not in content
    assert "scaffold_image" not in content
    assert len(result["artifacts"]) == 2
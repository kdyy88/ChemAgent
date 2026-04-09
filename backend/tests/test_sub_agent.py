"""Unit tests for the Sub-Agent system.

Coverage:
- tool_registry: whitelist correctness, ALWAYS_DENIED enforcement, custom mode
- sub_agent_prompts: persona prompt generation, anti-recursion fragment presence
- sub_graph: node topology, bypass_hitl, missing checkpointer guard
- tool_run_sub_agent: deterministic sub_thread_id, context truncation helpers
- anti-recursion contract: run_sub_agent absent from all mode tool sets
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.sub_agent_prompts import SubAgentMode, get_sub_agent_prompt
from app.agents.tool_registry import ALWAYS_DENIED, get_tools_for_mode


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def all_tool_names() -> set[str]:
    """Return the set of all available tool names from ALL_CHEM_TOOLS."""
    from app.agents.lg_tools import ALL_CHEM_TOOLS
    return {t.name for t in ALL_CHEM_TOOLS}


# ── tool_registry tests ───────────────────────────────────────────────────────


class TestToolRegistry:
    """Permission matrix, deny-list enforcement, custom mode validation."""

    def test_explore_tools_are_readonly(self) -> None:
        tools = get_tools_for_mode(SubAgentMode.explore)
        names = {t.name for t in tools}
        # Must include key discovery tools
        assert "tool_validate_smiles" in names
        assert "tool_pubchem_lookup" in names
        assert "tool_web_search" in names
        assert "tool_compute_descriptors" in names
        # Must NOT include destructive synthesis/prep tools
        assert "tool_build_3d_conformer" not in names
        assert "tool_prepare_pdbqt" not in names

    def test_plan_mode_has_no_tools(self) -> None:
        tools = get_tools_for_mode(SubAgentMode.plan)
        assert tools == [], "plan mode must have zero tools (pure LLM)"

    def test_general_mode_includes_full_rdkit_and_babel(self) -> None:
        tools = get_tools_for_mode(SubAgentMode.general)
        names = {t.name for t in tools}
        # Full RDKit
        assert "tool_validate_smiles" in names
        assert "tool_compute_descriptors" in names
        assert "tool_render_smiles" in names
        # Full Babel
        assert "tool_build_3d_conformer" in names
        assert "tool_prepare_pdbqt" in names
        assert "tool_convert_format" in names

    def test_always_denied_absent_from_every_mode(self, all_tool_names: set[str]) -> None:
        """ALWAYS_DENIED tools must be absent from all modes, no exceptions."""
        for mode in SubAgentMode:
            tools = get_tools_for_mode(mode)
            names = {t.name for t in tools}
            for denied in ALWAYS_DENIED:
                assert denied not in names, (
                    f"Denied tool '{denied}' found in mode '{mode.value}' tool set!"
                )

    def test_run_sub_agent_never_in_any_mode(self) -> None:
        """Anti-recursion: run_sub_agent must never appear in sub-agent tools."""
        for mode in SubAgentMode:
            tools = get_tools_for_mode(mode)
            names = {t.name for t in tools}
            assert "tool_run_sub_agent" not in names, (
                f"tool_run_sub_agent found in mode '{mode.value}' — recursion risk!"
            )

    def test_ask_human_never_in_any_mode(self) -> None:
        """HITL clarification is exclusive to the root agent."""
        for mode in SubAgentMode:
            tools = get_tools_for_mode(mode)
            names = {t.name for t in tools}
            assert "tool_ask_human" not in names

    def test_update_task_status_never_in_any_mode(self) -> None:
        """Task tracking is owned by the root planner."""
        for mode in SubAgentMode:
            tools = get_tools_for_mode(mode)
            names = {t.name for t in tools}
            assert "tool_update_task_status" not in names

    def test_custom_mode_with_valid_tools(self) -> None:
        tools = get_tools_for_mode(
            SubAgentMode.custom,
            ["tool_validate_smiles", "tool_pubchem_lookup"],
        )
        names = {t.name for t in tools}
        assert "tool_validate_smiles" in names
        assert "tool_pubchem_lookup" in names

    def test_custom_mode_invalid_tool_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown tool names"):
            get_tools_for_mode(SubAgentMode.custom, ["nonexistent_tool_xyz"])

    def test_custom_mode_denied_tool_silently_stripped(self) -> None:
        """Denied tools in custom whitelist are stripped without error."""
        tools = get_tools_for_mode(
            SubAgentMode.custom,
            ["tool_validate_smiles", "tool_run_sub_agent", "tool_ask_human"],
        )
        names = {t.name for t in tools}
        assert "tool_validate_smiles" in names
        assert "tool_run_sub_agent" not in names
        assert "tool_ask_human" not in names

    def test_custom_mode_no_tools_returns_empty(self) -> None:
        tools = get_tools_for_mode(SubAgentMode.custom, [])
        assert tools == []

    def test_custom_mode_none_tools_returns_empty(self) -> None:
        tools = get_tools_for_mode(SubAgentMode.custom, None)
        assert tools == []


# ── sub_agent_prompts tests ───────────────────────────────────────────────────


class TestSubAgentPrompts:
    """Persona prompt content and invariants."""

    def test_all_modes_produce_non_empty_prompt(self) -> None:
        for mode in SubAgentMode:
            prompt = get_sub_agent_prompt(mode)
            assert len(prompt) > 50, f"Prompt for mode '{mode.value}' is too short"

    def test_anti_recursion_present_in_all_modes(self) -> None:
        for mode in SubAgentMode:
            prompt = get_sub_agent_prompt(mode)
            assert "不能调用 tool_run_sub_agent" in prompt or "tool_run_sub_agent" in prompt, (
                f"Anti-recursion reminder missing from '{mode.value}' prompt"
            )

    def test_explore_mentions_readonly(self) -> None:
        prompt = get_sub_agent_prompt(SubAgentMode.explore)
        assert "只读" in prompt or "read" in prompt.lower()
        assert "最多 6 个一级要点" in prompt

    def test_plan_mentions_markdown(self) -> None:
        prompt = get_sub_agent_prompt(SubAgentMode.plan)
        assert "Markdown" in prompt or "markdown" in prompt.lower()

    def test_plan_mentions_no_tools(self) -> None:
        prompt = get_sub_agent_prompt(SubAgentMode.plan)
        # Plan should explicitly state no tool calls
        assert "工具" in prompt

    def test_custom_mode_injects_custom_instructions(self) -> None:
        instructions = "专注于配体的分子量必须低于 300 Da 的筛选条件"
        prompt = get_sub_agent_prompt(SubAgentMode.custom, custom_instructions=instructions)
        assert instructions in prompt

    def test_custom_mode_fallback_without_instructions(self) -> None:
        prompt = get_sub_agent_prompt(SubAgentMode.custom, custom_instructions="")
        assert len(prompt) > 50  # Falls back to default body

    def test_explore_prompt_forces_chem_tools(self) -> None:
        prompt = get_sub_agent_prompt(SubAgentMode.explore)
        assert "tool_murcko_scaffold" in prompt
        assert "tool_pubchem_lookup" in prompt
        assert "官能团" in prompt


# ── sub_graph tests ───────────────────────────────────────────────────────────


class TestSubGraphBuilder:
    """Graph topology and safety guards."""

    def test_raises_without_checkpointer(self) -> None:
        from app.agents.sub_graph import build_sub_agent_graph

        tools = get_tools_for_mode(SubAgentMode.explore)
        with pytest.raises(ValueError, match="persistent checkpointer"):
            build_sub_agent_graph(SubAgentMode.explore, tools, checkpointer=None)

    def test_plan_mode_has_single_node(self) -> None:
        from app.agents.sub_graph import build_sub_agent_graph
        from langgraph.checkpoint.memory import MemorySaver

        # Use in-memory saver for unit tests (HITL tested separately)
        mem_checkpointer = MemorySaver()
        tools = get_tools_for_mode(SubAgentMode.plan)  # empty
        assert tools == []

        graph = build_sub_agent_graph(SubAgentMode.plan, tools, mem_checkpointer)
        # plan graph: START → sub_agent → END (no sub_tools_executor)
        assert "sub_agent" in graph.get_graph().nodes
        assert "sub_tools_executor" not in graph.get_graph().nodes

    def test_explore_mode_has_two_nodes(self) -> None:
        from app.agents.sub_graph import build_sub_agent_graph
        from langgraph.checkpoint.memory import MemorySaver

        mem_checkpointer = MemorySaver()
        tools = get_tools_for_mode(SubAgentMode.explore)
        assert len(tools) > 0

        graph = build_sub_agent_graph(SubAgentMode.explore, tools, mem_checkpointer)
        node_names = set(graph.get_graph().nodes)
        assert "sub_agent" in node_names
        assert "sub_tools_executor" in node_names

    def test_general_mode_has_two_nodes(self) -> None:
        from app.agents.sub_graph import build_sub_agent_graph
        from langgraph.checkpoint.memory import MemorySaver

        mem_checkpointer = MemorySaver()
        tools = get_tools_for_mode(SubAgentMode.general)
        graph = build_sub_agent_graph(SubAgentMode.general, tools, mem_checkpointer)
        node_names = set(graph.get_graph().nodes)
        assert "sub_agent" in node_names
        assert "sub_tools_executor" in node_names


# ── tool_run_sub_agent helpers ────────────────────────────────────────────────


class TestSubAgentToolHelpers:
    """Deterministic thread ID and context truncation."""

    def test_deterministic_sub_thread_id_is_stable(self) -> None:
        from app.agents.tools.sub_agent import _deterministic_sub_thread_id

        tid1 = _deterministic_sub_thread_id("session-abc", "explore", "Compute Lipinski properties")
        tid2 = _deterministic_sub_thread_id("session-abc", "explore", "Compute Lipinski properties")
        assert tid1 == tid2, "Same inputs must produce same sub_thread_id"

    def test_deterministic_sub_thread_id_differs_by_task(self) -> None:
        from app.agents.tools.sub_agent import _deterministic_sub_thread_id

        tid1 = _deterministic_sub_thread_id("session-abc", "explore", "Task A")
        tid2 = _deterministic_sub_thread_id("session-abc", "explore", "Task B")
        assert tid1 != tid2

    def test_deterministic_sub_thread_id_differs_by_mode(self) -> None:
        from app.agents.tools.sub_agent import _deterministic_sub_thread_id

        tid1 = _deterministic_sub_thread_id("session-abc", "explore", "Task X")
        tid2 = _deterministic_sub_thread_id("session-abc", "general", "Task X")
        assert tid1 != tid2

    def test_deterministic_sub_thread_id_has_prefix(self) -> None:
        from app.agents.tools.sub_agent import _deterministic_sub_thread_id

        tid = _deterministic_sub_thread_id("session-abc", "plan", "Design a workflow")
        assert tid.startswith("sub_")

    def test_context_not_truncated_when_short(self) -> None:
        from app.agents.tools.sub_agent import _truncate_context

        short = "A" * 100
        assert _truncate_context(short) == short

    def test_context_truncated_at_8000_chars(self) -> None:
        from app.agents.tools.sub_agent import _MAX_CONTEXT_CHARS, _truncate_context

        long_ctx = "X" * (_MAX_CONTEXT_CHARS + 1000)
        truncated = _truncate_context(long_ctx)
        assert len(truncated) < len(long_ctx)
        assert "截断" in truncated

    def test_condense_sub_agent_response_keeps_core_points(self) -> None:
        from app.agents.tools.sub_agent import _condense_sub_agent_response

        response = """# 共同母核特征
- 保留双杂芳环 hinge binder。
- 需要疏水延伸至后口袋。

长段背景介绍：""" + ("A" * 1500)

        condensed = _condense_sub_agent_response(response)
        assert "共同母核特征" in condensed
        assert "双杂芳环 hinge binder" in condensed
        assert len(condensed) < len(response)

    def test_preflight_rejects_explore_design_with_forbid_new_smiles(self) -> None:
        from app.agents.tools.sub_agent import (
            _preflight_sub_agent_request,
            SubAgentOutputContract,
            SubAgentSmilesPolicy,
            SubAgentTaskKind,
        )

        mode, payload = _preflight_sub_agent_request(
            mode=SubAgentMode.explore,
            task="设计一个新的 scaffold hop 候选并输出 SMILES",
            context="给出 1 个候选新骨架",
            task_kind=SubAgentTaskKind.propose_scaffold,
            output_contract=SubAgentOutputContract.candidate_package,
            smiles_policy=SubAgentSmilesPolicy.forbid_new,
        )

        assert mode == SubAgentMode.explore
        assert payload is not None
        assert payload["status"] == "policy_conflict"
        assert payload["recommended_mode"] == "general"

    def test_preflight_allows_fact_only_scaffold_analysis_in_explore_mode(self) -> None:
        from app.agents.tools.sub_agent import (
            _preflight_sub_agent_request,
            SubAgentOutputContract,
            SubAgentSmilesPolicy,
            SubAgentTaskKind,
        )

        mode, payload = _preflight_sub_agent_request(
            mode=SubAgentMode.explore,
            task="调研已获批 MET 激酶抑制剂，提取 Murcko scaffold 并总结共同结构特征；不要设计新分子。",
            context="仅做事实调研与骨架比较：不做任何新分子设计/不输出任何候选 SMILES。",
            task_kind=SubAgentTaskKind.compare_scaffolds,
            output_contract=SubAgentOutputContract.json_findings,
            smiles_policy=SubAgentSmilesPolicy.forbid_new,
        )

        assert mode == SubAgentMode.explore
        assert payload is None

    def test_tool_schema_excludes_always_denied(self) -> None:
        """The tool's schema description should not expose denied tool names."""
        from app.agents.tools.sub_agent import tool_run_sub_agent

        schema = tool_run_sub_agent.args_schema.model_json_schema()
        schema_text = json.dumps(schema)
        # run_sub_agent itself should not be mentioned in LLM-facing schema
        assert "tool_run_sub_agent" not in schema_text

    def test_infer_required_mode(self) -> None:
        from app.agents.tools.sub_agent import _infer_required_mode

        assert _infer_required_mode("please build 3D conformer for this ligand") == SubAgentMode.general
        assert _infer_required_mode("extract the scaffold and compare similarity") == SubAgentMode.explore
        assert _infer_required_mode("write a concise summary") is None

    @pytest.mark.asyncio
    async def test_build_inherited_context_block_with_missing_artifact(self) -> None:
        from app.agents.tools.sub_agent import _build_inherited_context_block

        with patch("app.agents.tools.sub_agent.get_engine_artifact", AsyncMock(return_value=None)):
            block = await _build_inherited_context_block(["art_ghost"], "CCO", "")

        assert "art_ghost" in block
        assert "Error: Artifact not found or expired" in block

    @pytest.mark.asyncio
    async def test_build_inherited_context_block_auto_injects_active_smiles(self) -> None:
        from app.agents.tools.sub_agent import _build_inherited_context_block

        block = await _build_inherited_context_block([], "CCO", "")
        assert "[System Auto-Inject]" in block
        assert "CCO" in block

    @pytest.mark.asyncio
    async def test_build_inherited_context_block_includes_workspace_summary(self) -> None:
        from app.agents.tools.sub_agent import _build_inherited_context_block

        block = await _build_inherited_context_block(
            [],
            "CCO",
            "",
            None,
            "- 乙醇 | active_smiles=CCO | formula=C2H6O | MW=46.07",
        )

        assert "Structured Molecule Workspace" in block
        assert "乙醇" in block


# ── integration: run_sub_agent tool with mocked sub-graph ────────────────────


class TestRunSubAgentToolIntegration:
    """Integration tests with mocked LLM and sub-graph execution."""

    @pytest.mark.asyncio
    async def test_plan_mode_returns_ok_status(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agents.tools.sub_agent import tool_run_sub_agent

        fake_final_state = {
            "messages": [AIMessage(content="# 计划\n1. 验证 SMILES\n2. 计算描述符")],
            "artifacts": [],
            "tasks": [],
            "is_complex": False,
            "active_smiles": None,
        }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=fake_final_state)
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=[]))

        mock_checkpointer = MagicMock()

        with (
            patch("app.agents.tools.sub_agent.build_sub_agent_graph", return_value=mock_graph),
            patch("app.agents.runtime.get_checkpointer", return_value=mock_checkpointer),
        ):
            result_str = await tool_run_sub_agent.ainvoke(
                {
                    "mode": "plan",
                    "task": "为布洛芬的 Lipinski 分析设计执行步骤",
                    "context": "",
                }
            )

        result = json.loads(result_str)
        assert result["status"] == "ok"
        assert result["mode"] == "plan"
        assert "计划" in result["response"] or len(result["response"]) > 0
        assert result["result"] == result["response"]
        assert result["task_kind"] == "validate_candidate"
        assert isinstance(result["findings"], list)

    @pytest.mark.asyncio
    async def test_run_sub_agent_returns_produced_artifacts_and_suggested_smiles(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agents.tools.sub_agent import tool_run_sub_agent

        fake_final_state = {
            "messages": [AIMessage(content="已生成新分子并完成评估")],
            "artifacts": [{"artifact_id": "art_sub_new", "smiles": "N#CC1=CC=CC=C1"}],
            "molecule_workspace": [
                {
                    "key": "smiles:N#CC1=CC=CC=C1",
                    "primary_name": "新骨架分子",
                    "canonical_smiles": "N#CC1=CC=CC=C1",
                    "scaffold_smiles": "c1ccccc1",
                }
            ],
            "tasks": [],
            "is_complex": False,
            "active_smiles": "N#CC1=CC=CC=C1",
        }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=fake_final_state)
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=[]))

        mock_checkpointer = MagicMock()

        with (
            patch("app.agents.tools.sub_agent.build_sub_agent_graph", return_value=mock_graph),
            patch("app.agents.runtime.get_checkpointer", return_value=mock_checkpointer),
            patch("app.agents.tools.sub_agent.get_engine_artifact", AsyncMock(return_value=None)),
            patch(
                "app.agents.tools.sub_agent._lg_get_config",
                create=True,
                return_value={
                    "configurable": {
                        "thread_id": "parent-thread",
                        "parent_active_smiles": "CCO",
                        "parent_active_artifact_id": "art_parent",
                        "parent_molecule_workspace_summary": "- 乙醇 | active_smiles=CCO | formula=C2H6O",
                    }
                },
            ),
        ):
            result_str = await tool_run_sub_agent.ainvoke(
                {
                    "mode": "explore",
                    "task": "分析新的骨架结果",
                    "artifact_ids": ["art_parent"],
                }
            )

        result = json.loads(result_str)
        assert result["status"] == "ok"
        assert result["produced_artifacts"][0]["artifact_id"] == "art_sub_new"
        assert result["suggested_active_smiles"] == "N#CC1=CC=CC=C1"
        assert result["molecule_workspace"][0]["primary_name"] == "新骨架分子"
        assert "findings" in result
        assert "candidate_cores" in result

    @pytest.mark.asyncio
    async def test_explore_design_request_with_forbid_new_smiles_returns_policy_conflict(self) -> None:
        from app.agents.tools.sub_agent import tool_run_sub_agent

        result_str = await tool_run_sub_agent.ainvoke(
            {
                "mode": "explore",
                "task": "设计一个不含咪唑的新骨架并给出候选 SMILES",
                "task_kind": "propose_scaffold",
                "output_contract": "candidate_package",
                "smiles_policy": "forbid_new",
            }
        )

        result = json.loads(result_str)
        assert result["status"] == "policy_conflict"
        assert result["needs_followup"] is True
        assert result["recommended_mode"] == "general"

    @pytest.mark.asyncio
    async def test_unknown_mode_returns_error(self) -> None:
        from app.agents.tools.sub_agent import tool_run_sub_agent

        result_str = await tool_run_sub_agent.ainvoke(
            {
                "mode": "invalid_mode_xyz",
                "task": "Some task",
            }
        )
        result = json.loads(result_str)
        assert result["status"] == "error"
        assert "Unknown sub-agent mode" in result["error"]

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_status(self) -> None:
        import asyncio

        from app.agents.tools.sub_agent import tool_run_sub_agent

        async def slow_ainvoke(*args: object, **kwargs: object) -> dict:  # noqa: ARG001
            await asyncio.sleep(999)
            return {}

        mock_graph = AsyncMock()
        mock_graph.ainvoke = slow_ainvoke
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=[]))

        mock_checkpointer = MagicMock()

        with (
            patch("app.agents.tools.sub_agent.build_sub_agent_graph", return_value=mock_graph),
            patch("app.agents.runtime.get_checkpointer", return_value=mock_checkpointer),
            patch("app.agents.tools.sub_agent._SUB_AGENT_TIMEOUT", 0.05),
        ):
            result_str = await tool_run_sub_agent.ainvoke(
                {
                    "mode": "explore",
                    "task": "Task that will timeout",
                }
            )

        result = json.loads(result_str)
        assert result["status"] == "timeout"

    @pytest.mark.asyncio
    async def test_custom_invalid_tool_returns_error(self) -> None:
        from app.agents.tools.sub_agent import tool_run_sub_agent

        mock_checkpointer = MagicMock()

        with patch("app.agents.runtime.get_checkpointer", return_value=mock_checkpointer):
            result_str = await tool_run_sub_agent.ainvoke(
                {
                    "mode": "custom",
                    "task": "Some task",
                    "custom_tools": ["nonexistent_tool_xyz"],
                }
            )

        result = json.loads(result_str)
        assert result["status"] == "error"
        assert "Unknown tool names" in result["error"]

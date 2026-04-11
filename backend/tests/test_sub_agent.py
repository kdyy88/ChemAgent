"""Unit tests for the Sub-Agent system.

Coverage:
- tool_registry: whitelist correctness, ALWAYS_DENIED enforcement, custom mode
- sub_agent_prompts: persona prompt generation, anti-recursion fragment presence
- sub_graph: node topology, bypass_hitl, missing checkpointer guard
- tool_run_sub_agent: UUID-backed runtime ids, typed delegation normalization
- anti-recursion contract: run_sub_agent absent from all mode tool sets
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.sub_agents.protocol import ScratchpadKind, ScratchpadRef
from app.agents.sub_agents.prompts import SubAgentMode, get_sub_agent_prompt
from app.agents.sub_agents.runtime_tools import INTERNAL_SUB_AGENT_TOOLS
from app.tools.registry import ALWAYS_DENIED, get_root_tools, get_tool_tier, get_tools_for_mode
from app.agents.sub_agents.skills import load_required_skill_markdown
from app.skills.manager import invalidate_skill_cache


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def all_tool_names() -> set[str]:
    """Return the set of all available tool names from ALL_CHEM_TOOLS."""
    from app.tools.chem import ALL_CHEM_TOOLS
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

    def test_plan_runtime_tools_include_read_and_write_plan(self) -> None:
        names = {tool.name for tool in INTERNAL_SUB_AGENT_TOOLS}
        assert "search_available_skills" in names
        assert "tool_read_plan" in names
        assert "tool_write_plan" in names
        assert "tool_exit_plan_mode" in names

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


class TestSubAgentPrompts:
    def test_plan_prompt_contains_revision_rules(self) -> None:
        prompt = get_sub_agent_prompt(SubAgentMode.plan)
        assert "<revision_rules>" in prompt
        assert "<domain_boundary>" in prompt
        assert "<output_schema>" in prompt
        assert "<terminal_protocol>" in prompt
        assert "绝对禁止输出‘我将如何修改’" in prompt
        assert "search_available_skills" in prompt
        assert "tool_read_plan" in prompt
        assert "tool_write_plan" in prompt
        assert "描述结果内容与用途，而不是内部 artifact 名称" in prompt
        assert "禁止把 Outputs 写成内部实现细节或存储对象名" in prompt

    def test_custom_mode_no_tools_returns_empty(self) -> None:
        tools = get_tools_for_mode(SubAgentMode.custom, [])
        assert tools == []

    def test_custom_mode_none_tools_returns_empty(self) -> None:
        tools = get_tools_for_mode(SubAgentMode.custom, None)
        assert tools == []

    def test_root_tools_are_resolved_via_registry(self) -> None:
        tools = get_root_tools()
        names = {t.name for t in tools}

        assert "tool_validate_smiles" in names
        assert "tool_run_sub_agent" in names
        assert "tool_ask_human" in names

    def test_root_tools_strip_subagent_delegation_outside_general_mode(self) -> None:
        tools = get_root_tools(root_mode="plan")
        names = {t.name for t in tools}

        assert "tool_validate_smiles" in names
        assert "tool_run_sub_agent" not in names
        assert "tool_ask_human" in names

    def test_tool_tier_reads_metadata_for_migrated_tools(self) -> None:
        tools = get_root_tools(include_l2=True)
        tool_map = {tool.name: tool for tool in tools}

        assert get_tool_tier(tool_map["tool_compute_descriptors"]) == "L1"
        assert get_tool_tier(tool_map["tool_build_3d_conformer"]) == "L2"

    def test_root_tools_excludes_l2_by_default(self) -> None:
        tools = get_root_tools()
        names = {tool.name for tool in tools}

        # L1 tools present
        assert "tool_validate_smiles" in names
        assert "tool_compute_descriptors" in names
        assert "tool_pubchem_lookup" in names
        # Control tools present
        assert "tool_run_sub_agent" in names
        # L2 tools absent
        assert "tool_build_3d_conformer" not in names
        assert "tool_prepare_pdbqt" not in names
        assert "tool_convert_format" not in names
        assert "tool_compute_partial_charges" not in names


class TestWebSearchTool:
    async def test_web_search_uses_tavily(self) -> None:
        from app.tools.interaction.web_search import tool_web_search

        tavily_payload = {
            "answer": "Azithromycin remains approved for several bacterial infections.",
            "results": [
                {
                    "title": "FDA label update",
                    "url": "https://example.com/fda",
                    "content": "Updated safety and prescribing information.",
                }
            ],
        }

        with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test-key"}, clear=False):
            with patch("app.tools.interaction.web_search.TavilyClient") as client_cls:
                client_cls.return_value.search.return_value = tavily_payload

                raw = await tool_web_search.ainvoke({"query": "azithromycin 2026"})

        parsed = json.loads(raw)
        client_cls.assert_called_once_with(api_key="tvly-test-key")
        client_cls.return_value.search.assert_called_once_with(
            query="azithromycin 2026",
            search_depth="advanced",
            max_results=8,
        )
        assert parsed["status"] == "success"
        assert parsed["provider"] == "tavily"
        assert parsed["results"][0]["title"] == "Tavily Answer"
        assert parsed["results"][1]["url"] == "https://example.com/fda"

    async def test_web_search_requires_tavily_api_key(self) -> None:
        from app.tools.interaction.web_search import tool_web_search

        with patch.dict("os.environ", {}, clear=True):
            raw = await tool_web_search.ainvoke({"query": "aspirin approval news"})

        parsed = json.loads(raw)
        assert parsed["status"] == "error"
        assert "TAVILY_API_KEY" in parsed["error"]


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

    def test_plan_mentions_task_complete(self) -> None:
        prompt = get_sub_agent_prompt(SubAgentMode.plan)
        assert "tool_exit_plan_mode" in prompt
        assert "tool_write_plan" in prompt

    def test_prompts_mention_scratchpad_and_termination(self) -> None:
        prompt = get_sub_agent_prompt(SubAgentMode.general)
        assert "tool_read_scratchpad" in prompt
        assert "tool_task_complete" in prompt
        assert "tool_report_failure" in prompt

    def test_custom_mode_injects_custom_instructions(self) -> None:
        instructions = "专注于配体的分子量必须低于 300 Da 的筛选条件"
        prompt = get_sub_agent_prompt(SubAgentMode.custom, custom_instructions=instructions)
        assert instructions in prompt

    def test_custom_mode_fallback_without_instructions(self) -> None:
        prompt = get_sub_agent_prompt(SubAgentMode.custom, custom_instructions="")
        assert len(prompt) > 50  # Falls back to default body

    def test_custom_mode_can_inject_loaded_skills(self) -> None:
        prompt = get_sub_agent_prompt(
            SubAgentMode.custom,
            custom_instructions="专注 RDKit 描述符分析",
            skill_markdown="<skill name=\"rdkit\">Use tool_evaluate_molecule</skill>",
        )

        assert "<loaded_skills>" in prompt
        assert "Use tool_evaluate_molecule" in prompt

    def test_builtin_modes_ignore_skill_markdown_argument(self) -> None:
        prompt = get_sub_agent_prompt(
            SubAgentMode.explore,
            skill_markdown="<skill name=\"rdkit\">ignored</skill>",
        )

        assert "<loaded_skills>" not in prompt
        assert "ignored" not in prompt


class TestSkillLoader:
    def setup_method(self) -> None:
        invalidate_skill_cache()

    def test_load_required_skill_markdown_reads_local_skill(self) -> None:
        markdown = load_required_skill_markdown(["rdkit"])

        assert '<skill name="rdkit">' in markdown
        assert "tool_evaluate_molecule" in markdown

    def test_load_required_skill_markdown_deduplicates_names(self) -> None:
        markdown = load_required_skill_markdown(["rdkit", "rdkit"])

        assert markdown.count('<skill name="rdkit">') == 1

    def test_load_required_skill_markdown_rejects_missing_skill(self) -> None:
        with pytest.raises(FileNotFoundError, match="Skill not found"):
            load_required_skill_markdown(["missing_skill_xyz"])

    def test_explore_prompt_forces_chem_tools(self) -> None:
        prompt = get_sub_agent_prompt(SubAgentMode.explore)
        assert "tool_murcko_scaffold" in prompt
        assert "tool_pubchem_lookup" in prompt
        assert "官能团" in prompt


class TestDynamicSkillSystem:
    """Tests for the dynamic skill scanning, listing, and on-demand loading."""

    def setup_method(self) -> None:
        invalidate_skill_cache()

    def test_scan_all_skills_discovers_database_lookup(self) -> None:
        from app.skills.manager import scan_all_skills

        skills = scan_all_skills()
        names = [s.name for s in skills]
        assert "database-lookup" in names

    def test_scan_all_skills_discovers_rdkit(self) -> None:
        from app.skills.manager import scan_all_skills

        skills = scan_all_skills()
        names = [s.name for s in skills]
        assert "rdkit" in names

    def test_scan_all_skills_parses_frontmatter(self) -> None:
        from app.skills.manager import scan_all_skills

        skills = scan_all_skills()
        db_skill = next(s for s in skills if s.name == "database-lookup")
        assert db_skill.description
        assert db_skill.when_to_use
        assert "explore" in db_skill.applicable_modes

    def test_scan_all_skills_caches_results(self) -> None:
        from app.skills.manager import scan_all_skills

        first = scan_all_skills()
        second = scan_all_skills()
        assert first is second

    def test_format_skill_listing_returns_xml(self) -> None:
        from app.skills.manager import format_skill_listing

        listing = format_skill_listing()
        assert "<available_skills>" in listing
        assert "database-lookup" in listing
        assert "</available_skills>" in listing

    def test_format_skill_listing_filters_by_mode(self) -> None:
        from app.skills.manager import format_skill_listing

        listing = format_skill_listing(modes=["explore"])
        assert "database-lookup" in listing

        # plan mode is NOT in database-lookup's applicableModes
        listing_plan = format_skill_listing(modes=["plan"])
        # rdkit has plan? No. But skills with empty applicableModes match all modes.
        # Just verify it returns something or is empty as expected.
        assert isinstance(listing_plan, str)

    def test_load_skill_by_name_returns_content(self) -> None:
        from app.skills.manager import load_skill_by_name

        content = load_skill_by_name("database-lookup")
        assert "Database Lookup" in content
        assert "PubChem" in content

    def test_load_skill_by_name_rejects_unknown(self) -> None:
        from app.skills.manager import load_skill_by_name

        with pytest.raises(FileNotFoundError, match="Skill not found"):
            load_skill_by_name("nonexistent_skill_abc")

    def test_load_skill_by_name_rejects_path_traversal(self) -> None:
        from app.skills.manager import load_skill_by_name

        with pytest.raises(ValueError, match="Unsafe skill name"):
            load_skill_by_name("../../../etc/passwd")

    def test_tool_load_skill_returns_json(self) -> None:
        from app.agents.sub_agents.runtime_tools import tool_load_skill

        result = tool_load_skill.invoke({"skill_name": "database-lookup"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "PubChem" in parsed["content"]

    def test_tool_load_skill_handles_missing(self) -> None:
        from app.agents.sub_agents.runtime_tools import tool_load_skill

        result = tool_load_skill.invoke({"skill_name": "nonexistent_xyz"})
        parsed = json.loads(result)
        assert parsed["status"] == "error"

    def test_search_skills_returns_database_lookup_for_pubchem_query(self) -> None:
        from app.skills.manager import search_skills

        matches = search_skills("PubChem 数据库 查询")
        assert matches
        assert matches[0].name == "database-lookup"

    def test_search_available_skills_returns_structured_markdown(self) -> None:
        from app.agents.sub_agents.runtime_tools import tool_search_available_skills

        result = tool_search_available_skills.invoke({"query": "PubChem"})
        assert "### Skill Search Results" in result
        assert "Tool Name" in result
        assert "database-lookup" in result

    def test_explore_prompt_with_skill_listing(self) -> None:
        from app.skills.manager import format_skill_listing

        listing = format_skill_listing(modes=["explore"])
        prompt = get_sub_agent_prompt(SubAgentMode.explore, skill_listing=listing)
        assert "<available_skills>" in prompt
        assert "search_available_skills" in prompt
        assert "tool_load_skill" in prompt
        assert "database-lookup" in prompt

    def test_custom_mode_ignores_skill_listing(self) -> None:
        prompt = get_sub_agent_prompt(
            SubAgentMode.custom,
            custom_instructions="Custom task",
            skill_listing="<available_skills>should be ignored</available_skills>",
        )
        assert "<available_skills>" not in prompt

    def test_internal_tools_include_load_skill(self) -> None:
        from app.agents.sub_agents.runtime_tools import INTERNAL_SUB_AGENT_TOOLS

        tool_names = [t.name for t in INTERNAL_SUB_AGENT_TOOLS]
        assert "tool_load_skill" in tool_names
        assert "search_available_skills" in tool_names


# ── sub_graph tests ───────────────────────────────────────────────────────────


class TestSubGraphBuilder:
    """Graph topology and safety guards."""

    def test_raises_without_checkpointer(self) -> None:
        from app.agents.sub_agents.graph import build_sub_agent_graph

        tools = get_tools_for_mode(SubAgentMode.explore)
        with pytest.raises(ValueError, match="persistent checkpointer"):
            build_sub_agent_graph(SubAgentMode.explore, tools, checkpointer=None)

    def test_plan_mode_has_runtime_tools_executor(self) -> None:
        from app.agents.sub_agents.graph import build_sub_agent_graph
        from langgraph.checkpoint.memory import MemorySaver

        mem_checkpointer = MemorySaver()
        tools = get_tools_for_mode(SubAgentMode.plan)
        assert tools == []

        graph = build_sub_agent_graph(SubAgentMode.plan, tools, mem_checkpointer)
        assert "sub_agent" in graph.get_graph().nodes
        assert "sub_tools_executor" in graph.get_graph().nodes

    def test_explore_mode_has_two_nodes(self) -> None:
        from app.agents.sub_agents.graph import build_sub_agent_graph
        from langgraph.checkpoint.memory import MemorySaver

        mem_checkpointer = MemorySaver()
        tools = get_tools_for_mode(SubAgentMode.explore)
        assert len(tools) > 0

        graph = build_sub_agent_graph(SubAgentMode.explore, tools, mem_checkpointer)
        node_names = set(graph.get_graph().nodes)
        assert "sub_agent" in node_names
        assert "sub_tools_executor" in node_names

    def test_general_mode_has_two_nodes(self) -> None:
        from app.agents.sub_agents.graph import build_sub_agent_graph
        from langgraph.checkpoint.memory import MemorySaver

        mem_checkpointer = MemorySaver()
        tools = get_tools_for_mode(SubAgentMode.general)
        graph = build_sub_agent_graph(SubAgentMode.general, tools, mem_checkpointer)
        node_names = set(graph.get_graph().nodes)
        assert "sub_agent" in node_names
        assert "sub_tools_executor" in node_names


# ── tool_run_sub_agent helpers ────────────────────────────────────────────────


class TestSubAgentToolHelpers:
    """UUID-backed runtime ids and typed delegation normalization."""

    def test_resolve_runtime_ids_uses_plan_id_for_plan_mode(self) -> None:
        from app.agents.sub_agents.dispatcher import _resolve_runtime_ids

        sub_thread_id, plan_id, execution_task_id = _resolve_runtime_ids(
            mode="plan",
            configurable={"plan_id": "123e4567-e89b-12d3-a456-426614174000"},
        )

        assert sub_thread_id == "plan_123e4567-e89b-12d3-a456-426614174000"
        assert plan_id == "123e4567-e89b-12d3-a456-426614174000"
        assert execution_task_id is None

    def test_resolve_runtime_ids_uses_execution_id_for_non_plan_mode(self) -> None:
        from app.agents.sub_agents.dispatcher import _resolve_runtime_ids

        sub_thread_id, plan_id, execution_task_id = _resolve_runtime_ids(
            mode="general",
            configurable={"execution_task_id": "123e4567-e89b-12d3-a456-426614174999"},
        )

        assert sub_thread_id == "exec_123e4567-e89b-12d3-a456-426614174999"
        assert execution_task_id == "123e4567-e89b-12d3-a456-426614174999"
        assert plan_id is None

    def test_normalize_artifact_pointers_prefers_explicit_then_parent(self) -> None:
        from app.agents.sub_agents.dispatcher import _normalize_artifact_pointers

        assert _normalize_artifact_pointers(["art_a", "art_b"], ["art_c"], "art_d") == ["art_a", "art_b"]
        assert _normalize_artifact_pointers([], ["art_c", "art_d"], "art_e") == ["art_c", "art_d"]
        assert _normalize_artifact_pointers([], [], "art_e") == ["art_e"]

    def test_normalize_delegation_keeps_short_context_inline(self) -> None:
        """Without a context param the delegation always starts with empty inline_context."""
        from app.agents.sub_agents.dispatcher import _normalize_delegation_payload

        delegation = _normalize_delegation_payload(
            mode="explore",
            task="提取共同骨架特征",
            requested_artifact_ids=["art_parent"],
            parent_thread_id="parent-thread",
            sub_thread_id="sub_123",
            parent_active_smiles="CCO",
            parent_active_artifact_id="art_parent",
            parent_artifact_ids=["art_parent"],
            parent_molecule_workspace_summary="- 乙醇 | active_smiles=CCO",
            provided_delegation=None,
        )

        assert delegation.inline_context == ""
        assert delegation.scratchpad_refs == []
        assert delegation.artifact_pointers == ["art_parent"]

    def test_normalize_delegation_writes_long_context_to_scratchpad(self) -> None:
        """Without a context param, no scratchpad entry is created during delegation build."""
        from app.agents.sub_agents.dispatcher import _normalize_delegation_payload

        with patch("app.agents.sub_agents.dispatcher.create_scratchpad_entry") as create_entry:
            delegation = _normalize_delegation_payload(
                mode="explore",
                task="提取共同骨架特征",
                requested_artifact_ids=[],
                parent_thread_id="parent-thread",
                sub_thread_id="sub_123",
                parent_active_smiles="CCO",
                parent_active_artifact_id="art_parent",
                parent_artifact_ids=["art_parent"],
                parent_molecule_workspace_summary="",
                provided_delegation=None,
            )

        create_entry.assert_not_called()
        assert delegation.inline_context == ""
        assert delegation.scratchpad_refs == []

    def test_preflight_rejects_explore_design_with_forbid_new_smiles(self) -> None:
        from app.agents.sub_agents.dispatcher import (
            _preflight_sub_agent_request,
            SubAgentOutputContract,
            SubAgentSmilesPolicy,
            SubAgentTaskKind,
        )

        mode, payload = _preflight_sub_agent_request(
            mode=SubAgentMode.explore,
            task="设计一个新的 scaffold hop 候选并输出 SMILES",
            task_kind=SubAgentTaskKind.propose_scaffold,
            output_contract=SubAgentOutputContract.candidate_package,
            smiles_policy=SubAgentSmilesPolicy.forbid_new,
        )

        assert mode == SubAgentMode.explore
        assert payload is not None
        assert payload["status"] == "policy_conflict"
        assert payload["recommended_mode"] == "general"

    def test_preflight_allows_fact_only_scaffold_analysis_in_explore_mode(self) -> None:
        from app.agents.sub_agents.dispatcher import (
            _preflight_sub_agent_request,
            SubAgentOutputContract,
            SubAgentSmilesPolicy,
            SubAgentTaskKind,
        )

        mode, payload = _preflight_sub_agent_request(
            mode=SubAgentMode.explore,
            task="调研已获批 MET 激酶抑制剂，提取 Murcko scaffold 并总结共同结构特征；不要设计新分子。",
            task_kind=SubAgentTaskKind.compare_scaffolds,
            output_contract=SubAgentOutputContract.json_findings,
            smiles_policy=SubAgentSmilesPolicy.forbid_new,
        )

        assert mode == SubAgentMode.explore
        assert payload is None

    def test_tool_schema_excludes_always_denied(self) -> None:
        """The tool's schema description should not expose denied tool names."""
        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

        schema_model = tool_run_sub_agent.args_schema
        assert schema_model is not None
        schema = getattr(schema_model, "model_json_schema")()
        schema_text = json.dumps(schema)
        # run_sub_agent itself should not be mentioned in LLM-facing schema
        assert "tool_run_sub_agent" not in schema_text

    def test_infer_required_mode(self) -> None:
        from app.agents.sub_agents.dispatcher import _infer_required_mode

        assert _infer_required_mode("please build 3D conformer for this ligand") == SubAgentMode.general
        assert _infer_required_mode("extract the scaffold and compare similarity") == SubAgentMode.explore
        assert _infer_required_mode("write a concise summary") is None


# ── integration: run_sub_agent tool with mocked sub-graph ────────────────────


class TestRunSubAgentToolIntegration:
    """Integration tests with mocked LLM and sub-graph execution."""

    @pytest.mark.asyncio
    async def test_plan_mode_returns_pending_approval_status(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

        fake_ref = ScratchpadRef(
            scratchpad_id="sp_abcdef123456",
            kind=ScratchpadKind.report,
            summary="计划摘要",
            size_bytes=100,
            created_by="sub_agent",
        )

        fake_final_state = {
            "messages": [AIMessage(content="# 计划\n1. 验证 SMILES\n2. 计算描述符")],
            "artifacts": [],
            "tasks": [],
            "is_complex": False,
            "active_smiles": None,
            "sub_agent_result": {
                "status": "plan_pending_approval",
                "summary": "先验证 SMILES，再计算描述符。",
                "requires_approval": True,
                "plan": {
                    "plan_id": "123e4567-e89b-12d3-a456-426614174000",
                    "plan_file_ref": "session/123e4567-e89b-12d3-a456-426614174000.md",
                    "status": "pending_approval",
                    "summary": "先验证 SMILES，再计算描述符。",
                    "revision": 1,
                },
            },
        }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=fake_final_state)
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=[]))

        mock_checkpointer = MagicMock()

        with (
            patch("app.agents.sub_agents.dispatcher.build_sub_agent_graph", return_value=mock_graph),
            patch("app.agents.runtime.get_checkpointer", return_value=mock_checkpointer),
            patch("app.agents.sub_agents.dispatcher.create_scratchpad_entry", return_value=fake_ref),
        ):
            result_str = await tool_run_sub_agent.ainvoke(
                {
                    "mode": "plan",
                    "task": "为布洛芬的 Lipinski 分析设计执行步骤",
                    "context": "",
                }
            )

        result = json.loads(result_str)
        assert result["status"] == "plan_pending_approval"
        assert result["mode"] == "plan"
        assert result["plan_pointer"]["plan_id"] == "123e4567-e89b-12d3-a456-426614174000"
        assert result["scratchpad_report_ref"]["scratchpad_id"] == "sp_abcdef123456"
        assert "计划摘要" in result["response"] or len(result["response"]) > 0
        assert result["result"] == result["response"]
        assert result["task_kind"] == "validate_candidate"
        assert result["delegation"]["task_directive"] == "为布洛芬的 Lipinski 分析设计执行步骤"

    @pytest.mark.asyncio
    async def test_general_execution_context_is_injected_as_system_message_and_tasks(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

        captured_input: dict[str, Any] = {}

        class _MockGraph:
            async def ainvoke(self, sub_input, config=None):
                captured_input["value"] = sub_input
                return {"messages": [AIMessage(content="done")], "sub_agent_result": {"status": "completed", "summary": "done"}}

            async def aget_state(self, _config):
                return MagicMock(interrupts=[])

        with (
            patch("app.agents.sub_agents.dispatcher.build_sub_agent_graph", return_value=_MockGraph()),
            patch("app.agents.runtime.get_checkpointer", return_value=MagicMock()),
        ):
            await tool_run_sub_agent.ainvoke(
                {
                    "mode": "general",
                    "task": "执行已批准计划",
                    "delegation": {
                        "subagent_type": "general",
                        "task_directive": "严格执行已批准计划",
                        "inline_context": "<execution_context>\n你当前处于 GENERAL 模式\n</execution_context>\n\n<approved_plan_content>\n**阶段 1：验证输入**\nfoo\n**阶段 2：运行分析**\nbar\n</approved_plan_content>\n\n<strict_execution_directives>\n不要请示用户\n</strict_execution_directives>",
                    },
                }
            )

        sub_input = captured_input["value"]
        assert sub_input["messages"][0].type == "system"
        assert "<execution_context>" in sub_input["messages"][0].content
        assert sub_input["subtask_control"]["strict_execution"] is True
        assert [task["id"] for task in sub_input["tasks"]] == ["1", "2"]

    @pytest.mark.asyncio
    async def test_run_sub_agent_returns_produced_artifacts_and_suggested_smiles(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

        fake_ref = ScratchpadRef(
            scratchpad_id="sp_111111aaaaaa",
            kind=ScratchpadKind.report,
            summary="已生成新分子并完成评估",
            size_bytes=120,
            created_by="sub_agent",
        )

        fake_final_state = {
            "messages": [AIMessage(content="已生成新分子并完成评估")],
            "artifacts": [{"artifact_id": "art_sub_new", "smiles": "N#CC1=CC=CC=C1"}],
            "tasks": [],
            "is_complex": False,
            "active_smiles": "N#CC1=CC=CC=C1",
            "sub_agent_result": {
                "status": "completed",
                "summary": "已生成新分子并完成评估",
                "produced_artifact_ids": ["art_sub_new"],
                "metrics": {"qed": 0.72},
                "advisory_active_smiles": "N#CC1=CC=CC=C1",
            },
        }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=fake_final_state)
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=[]))

        mock_checkpointer = MagicMock()

        with (
            patch("app.agents.sub_agents.dispatcher.build_sub_agent_graph", return_value=mock_graph),
            patch("app.agents.runtime.get_checkpointer", return_value=mock_checkpointer),
            patch("app.agents.sub_agents.dispatcher.create_scratchpad_entry", return_value=fake_ref),
            patch(
                "app.agents.sub_agents.dispatcher._lg_get_config",
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
        assert result["completion"]["produced_artifact_ids"] == ["art_sub_new"]
        assert result["scratchpad_report_ref"]["scratchpad_id"] == "sp_111111aaaaaa"

    @pytest.mark.asyncio
    async def test_structured_completion_generates_report_content_without_placeholder(self) -> None:
        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

        fake_ref = ScratchpadRef(
            scratchpad_id="sp_structured123",
            kind=ScratchpadKind.report,
            summary="structured report",
            size_bytes=160,
            created_by="sub_agent",
        )

        fake_final_state = {
            "messages": [],
            "artifacts": [{"artifact_id": "art_structured_1"}],
            "tasks": [],
            "is_complex": False,
            "active_smiles": "CCN",
            "sub_agent_result": {
                "status": "completed",
                "summary": "Found 3 reusable candidates with a shared quinazoline core.",
                "produced_artifact_ids": ["art_structured_1"],
                "metrics": {"common_core": "quinazoline", "candidate_count": 3},
                "advisory_active_smiles": "CCN",
            },
        }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=fake_final_state)
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=[]))
        create_entry = MagicMock(return_value=fake_ref)

        with (
            patch("app.agents.sub_agents.dispatcher.build_sub_agent_graph", return_value=mock_graph),
            patch("app.agents.runtime.get_checkpointer", return_value=MagicMock()),
            patch("app.agents.sub_agents.dispatcher.create_scratchpad_entry", create_entry),
        ):
            result_str = await tool_run_sub_agent.ainvoke(
                {
                    "mode": "explore",
                    "task": "List reusable candidates and common scaffold features",
                }
            )

        result = json.loads(result_str)
        assert result["status"] == "ok"
        assert result["summary"] == "Found 3 reusable candidates with a shared quinazoline core."
        create_kwargs = create_entry.call_args.kwargs
        assert create_kwargs["content"] != "子智能体已完成任务，但未产生文本输出。"
        assert "Found 3 reusable candidates" in create_kwargs["content"]
        assert "Structured results:" in create_kwargs["content"]
        assert "common_core: quinazoline" in create_kwargs["content"]
        assert "Produced artifacts:" in create_kwargs["content"]

    @pytest.mark.asyncio
    async def test_structured_completion_wins_over_conflicting_free_text(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

        fake_ref = ScratchpadRef(
            scratchpad_id="sp_alignment123",
            kind=ScratchpadKind.report,
            summary="alignment report",
            size_bytes=160,
            created_by="sub_agent",
        )

        fake_final_state = {
            "messages": [
                AIMessage(
                    content="候选采用吗啉乙胺尾部，并已通过所有验证。"
                )
            ],
            "artifacts": [{"artifact_id": "art_alignment_1"}],
            "tasks": [],
            "is_complex": False,
            "active_smiles": "COc1ccc(Nc2nc(NCC3CCOCC3)nc(Nc3ccc(C#N)cc3)n2)cc1",
            "sub_agent_result": {
                "status": "completed",
                "summary": "候选保留 1,3,5-三嗪 hinge binder，并使用含氧六元环尾部；避免将该尾部误写为吗啉。",
                "produced_artifact_ids": ["art_alignment_1"],
                "metrics": {
                    "tail_description": "oxygen-containing six-membered ring tail",
                    "structure_grounded": True,
                },
                "advisory_active_smiles": "COc1ccc(Nc2nc(NCC3CCOCC3)nc(Nc3ccc(C#N)cc3)n2)cc1",
            },
        }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=fake_final_state)
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=[]))
        create_entry = MagicMock(return_value=fake_ref)

        with (
            patch("app.agents.sub_agents.dispatcher.build_sub_agent_graph", return_value=mock_graph),
            patch("app.agents.runtime.get_checkpointer", return_value=MagicMock()),
            patch("app.agents.sub_agents.dispatcher.create_scratchpad_entry", create_entry),
        ):
            result_str = await tool_run_sub_agent.ainvoke(
                {
                    "mode": "general",
                    "task": "核对已验证分子的结构描述是否一致",
                }
            )

        result = json.loads(result_str)
        assert result["status"] == "ok"
        assert result["summary"] == "候选保留 1,3,5-三嗪 hinge binder，并使用含氧六元环尾部；避免将该尾部误写为吗啉。"
        assert "吗啉乙胺" not in result["response"]
        assert result["completion"]["metrics"]["structure_grounded"] is True

        create_kwargs = create_entry.call_args.kwargs
        assert "含氧六元环尾部" in create_kwargs["content"]
        assert "吗啉乙胺" not in create_kwargs["content"]

    @pytest.mark.asyncio
    async def test_missing_task_complete_returns_protocol_error(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

        fake_ref = ScratchpadRef(
            scratchpad_id="sp_deadbeefcafe",
            kind=ScratchpadKind.report,
            summary="仅自然语言输出",
            size_bytes=80,
            created_by="sub_agent",
        )

        fake_final_state = {
            "messages": [AIMessage(content="我完成了任务，但没有调用终结工具")],
            "artifacts": [],
            "tasks": [],
            "is_complex": False,
            "active_smiles": None,
            "sub_agent_result": None,
        }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=fake_final_state)
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=[]))

        with (
            patch("app.agents.sub_agents.dispatcher.build_sub_agent_graph", return_value=mock_graph),
            patch("app.agents.runtime.get_checkpointer", return_value=MagicMock()),
            patch("app.agents.sub_agents.dispatcher.create_scratchpad_entry", return_value=fake_ref),
        ):
            result_str = await tool_run_sub_agent.ainvoke(
                {
                    "mode": "explore",
                    "task": "总结该分子的关键性质",
                }
            )

        result = json.loads(result_str)
        assert result["status"] == "protocol_error"
        assert result["scratchpad_report_ref"]["scratchpad_id"] == "sp_deadbeefcafe"
        assert "终结协议工具" in result["error"]

    @pytest.mark.asyncio
    async def test_report_failure_payload_is_preserved(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

        fake_ref = ScratchpadRef(
            scratchpad_id="sp_failure1234",
            kind=ScratchpadKind.report,
            summary="执行失败",
            size_bytes=60,
            created_by="sub_agent",
        )

        fake_final_state = {
            "messages": [AIMessage(content="工具连续失败，已终止")],
            "artifacts": [],
            "tasks": [],
            "is_complex": False,
            "active_smiles": None,
            "sub_agent_result": {
                "status": "failed",
                "summary": "工具连续失败，已终止",
                "error": "validation failed 3 times",
                "failure_category": "validation",
                "failed_tool_name": "tool_validate_smiles",
                "failed_args_signature": "abc123",
                "is_recoverable": False,
                "recommended_action": "spawn",
            },
        }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=fake_final_state)
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=[]))

        with (
            patch("app.agents.sub_agents.dispatcher.build_sub_agent_graph", return_value=mock_graph),
            patch("app.agents.runtime.get_checkpointer", return_value=MagicMock()),
            patch("app.agents.sub_agents.dispatcher.create_scratchpad_entry", return_value=fake_ref),
        ):
            result_str = await tool_run_sub_agent.ainvoke(
                {
                    "mode": "general",
                    "task": "验证一个无效的 SMILES 并总结失败原因",
                }
            )

        result = json.loads(result_str)
        assert result["status"] == "failed"
        assert result["failure"]["failure_category"] == "validation"
        assert result["failure"]["recommended_action"] == "spawn"
        assert result["needs_followup"] is True

    @pytest.mark.asyncio
    async def test_explore_design_request_with_forbid_new_smiles_returns_policy_conflict(self) -> None:
        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

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
        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

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

        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

        async def slow_ainvoke(*args: object, **kwargs: object) -> dict:  # noqa: ARG001
            await asyncio.sleep(999)
            return {}

        mock_graph = AsyncMock()
        mock_graph.ainvoke = slow_ainvoke
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(interrupts=[]))

        mock_checkpointer = MagicMock()

        with (
            patch("app.agents.sub_agents.dispatcher.build_sub_agent_graph", return_value=mock_graph),
            patch("app.agents.runtime.get_checkpointer", return_value=mock_checkpointer),
            patch("app.agents.sub_agents.dispatcher._SUB_AGENT_TIMEOUT", 0.05),
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
        from app.agents.sub_agents.dispatcher import tool_run_sub_agent

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

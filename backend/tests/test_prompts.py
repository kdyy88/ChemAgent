from __future__ import annotations

from app.agents.prompts import get_system_prompt


def test_system_prompt_includes_artifact_handoff_rules() -> None:
    prompt = get_system_prompt(
        {
            "active_smiles": "CCO",
            "active_artifact_id": "art_123",
            "task_plan": "- test",
            "is_native_reasoning_model": True,
        }
    )

    assert "artifact_pointers" in prompt
    assert "policy_conflicts" in prompt
    assert "needs_followup" in prompt


def test_system_prompt_requires_structured_completion_over_response() -> None:
    prompt = get_system_prompt(
        {
            "active_smiles": "CCO",
            "active_artifact_id": "art_123",
            "task_plan": "- test",
            "is_native_reasoning_model": True,
        }
    )

    # Sub-agent result consumption guidance (simplified in Skill-First refactor)
    assert "policy_conflicts" in prompt
    assert "needs_followup" in prompt


def test_sub_agent_prompt_forbids_speculative_ring_naming() -> None:
    from app.agents.sub_agents.prompts import SubAgentMode, get_sub_agent_prompt

    prompt = get_sub_agent_prompt(SubAgentMode.explore)

    assert "禁止仅凭‘含氧六元环’‘含氮六元环’" in prompt
    assert "若无法可靠命名某段取代基" in prompt
    assert "含氧六元环尾部" in prompt


def test_system_prompt_renders_artifact_warning() -> None:
    prompt = get_system_prompt(
        {
            "active_smiles": "CCO",
            "active_artifact_id": "art_123",
            "artifact_warning": "[Warning: Artifact art_123 is nearing expiration (600s remaining).]",
            "task_plan": "- test",
            "is_native_reasoning_model": True,
        }
    )

    assert "工件状态警告" in prompt
    assert "art_123" in prompt


def test_system_prompt_includes_task_output_and_locking_guidance() -> None:
    prompt = get_system_prompt(
        {
            "active_smiles": "CCO",
            "active_artifact_id": "art_123",
            "task_plan": "- [completed] 1. 提炼药效团\n  最近产出: 保留双芳环与酰胺氢键锚点",
            "is_native_reasoning_model": True,
        }
    )

    assert "summary" in prompt
    assert "已完成任务默认视为锁定" in prompt
    assert "最近产出" in prompt
    assert "in_progress" in prompt


def test_system_prompt_includes_structured_molecule_workspace_summary() -> None:
    prompt = get_system_prompt(
        {
            "active_artifact_id": "art_123",
            "viewport_content": "- 以下为当前 IDE 视口中的分子（优先以此表为准，旧工具消息因 history limit 被裁剪时尤甚）：\n\n| Artifact ID | SMILES | 状态 | MW | 诊断信息 |\n|---|---|---|---|---|\n| `mol_a` | `CCO` | staged | — | — |",
            "scratchpad_content": "- **核心目标**: 提升溶解度",
            "task_plan": "- test",
            "is_native_reasoning_model": True,
        }
    )

    assert "IDE 分子视口" in prompt
    assert "history limit" in prompt
    assert "CCO" in prompt


def test_system_prompt_includes_execution_failed_self_correction_rule() -> None:
    prompt = get_system_prompt(
        {
            "active_smiles": "CCO",
            "active_artifact_id": "art_123",
            "task_plan": "- test",
            "is_native_reasoning_model": True,
        }
    )

    assert "[Execution Failed]" in prompt
    assert "最多 3 次" in prompt
    assert "道歉" in prompt
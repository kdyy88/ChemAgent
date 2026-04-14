from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.nodes.golden_scenario import golden_scenario_node, route_from_planner


@pytest.mark.asyncio
async def test_golden_scenario_node_builds_workspace_and_pending_jobs() -> None:
    state = {
        "tasks": [
            {"id": "task_root", "description": "规范化母本", "status": "pending"},
            {"id": "task_rules", "description": "登记约束规则", "status": "pending"},
            {"id": "task_candidates", "description": "生成3个候选", "status": "pending"},
            {"id": "task_view", "description": "设置单视口", "status": "pending"},
            {"id": "task_conformer", "description": "提交3D任务", "status": "pending"},
        ],
        "scenario_kind": "scaffold_hop_mvp",
        "workspace_projection": None,
    }

    with patch("app.agents.nodes.golden_scenario.dispatch_task_update", new=AsyncMock()) as mocked_dispatch, patch(
        "app.agents.nodes.golden_scenario.submit_task_to_worker",
        new=AsyncMock(side_effect=[
            {"status": "queued", "task_id": "task_1"},
            {"status": "queued", "task_id": "task_2"},
            {"status": "queued", "task_id": "task_3"},
        ]),
    ):
        result = await golden_scenario_node(state, {"configurable": {"thread_id": "sess_1"}})

    workspace = result["workspace_projection"]
    assert workspace.root_handle == "root_molecule"
    assert workspace.candidate_handles == ["candidate_1", "candidate_2", "candidate_3"]
    assert len(result["pending_worker_tasks"]) == 3
    assert any(event["type"] == "workspace.snapshot" for event in result["workspace_events"])
    assert any(event["type"] == "workspace.delta" for event in result["workspace_events"])
    assert mocked_dispatch.await_count == 4


def test_route_from_planner_prefers_golden_scenario_for_mvp_state() -> None:
    assert route_from_planner({"scenario_kind": "scaffold_hop_mvp"}) == "golden_scenario"
    assert route_from_planner({}) == "chem_agent"
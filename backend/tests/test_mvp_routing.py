from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.agents.nodes.planner import planner_node
from app.agents.nodes.router import task_router_node


@pytest.mark.asyncio
async def test_router_detects_scaffold_hop_mvp_request() -> None:
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "以伊布替尼为母本，保留丙烯酰胺 warhead，要求并环吲哚新骨架，"
                    "做 scaffold hop，生成 3 个候选并比较。"
                )
            )
        ],
        "selected_model": None,
        "tasks": [],
    }

    result = await task_router_node(state, {})

    assert result["is_complex"] is True
    assert result["scenario_kind"] == "scaffold_hop_mvp"
    assert result["candidate_handles"] == ["candidate_1", "candidate_2", "candidate_3"]
    assert result["active_handle"] == "root_molecule"


@pytest.mark.asyncio
async def test_planner_uses_fixed_plan_for_scaffold_hop_mvp() -> None:
    state = {
        "scenario_kind": "scaffold_hop_mvp",
        "pending_approval_job_ids": [],
        "messages": [HumanMessage(content="golden path")],
    }

    with patch("app.agents.nodes.planner.dispatch_task_update", new=AsyncMock()) as mocked_dispatch:
        result = await planner_node(state, {})

    assert [task["description"] for task in result["tasks"]] == [
        "规范化母本",
        "登记约束规则",
        "生成3个候选",
        "设置单视口",
        "提交3D任务",
    ]
    assert result["candidate_generation_status"] == "planned"
    mocked_dispatch.assert_awaited_once()
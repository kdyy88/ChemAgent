from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.postprocessors import postprocess_build_3d_conformer
from app.services.task_runner.bridge import poll_task_result, run_via_worker, submit_task_to_worker, wait_for_task_result
from app.services.task_runner.worker import run_chem_task


@pytest.mark.asyncio
async def test_run_via_worker_returns_envelope_for_direct_fallback() -> None:
    with patch("app.services.task_runner.bridge.uuid4", return_value=SimpleNamespace(hex="abc123")), \
         patch("app.services.task_runner.bridge.get_arq_pool", new=AsyncMock(side_effect=RuntimeError("redis down"))), \
         patch("app.services.task_runner.bridge._run_direct", new=AsyncMock(return_value={"is_valid": True, "smiles": "CCO"})):
        result = await run_via_worker(
            "babel.build_3d_conformer",
            {"smiles": "CCO"},
            task_context={"workspace_job_id": "job_1", "workspace_target_handle": "root_molecule"},
            return_envelope=True,
        )

    assert result["task_id"] == "task_abc123"
    assert result["task_name"] == "babel.build_3d_conformer"
    assert result["delivery"] == "direct"
    assert result["task_context"]["workspace_job_id"] == "job_1"
    assert result["result"]["smiles"] == "CCO"


@pytest.mark.asyncio
async def test_submit_task_to_worker_returns_queued_envelope() -> None:
    fake_pool = SimpleNamespace(enqueue_job=AsyncMock())

    with patch("app.services.task_runner.bridge.uuid4", return_value=SimpleNamespace(hex="def456")), \
         patch("app.services.task_runner.bridge.get_arq_pool", new=AsyncMock(return_value=fake_pool)):
        result = await submit_task_to_worker(
            "babel.prepare_pdbqt",
            {"smiles": "CCO"},
            task_context={"workspace_job_id": "job_2"},
        )

    fake_pool.enqueue_job.assert_awaited_once_with(
        "run_chem_task",
        "babel.prepare_pdbqt",
        {"smiles": "CCO"},
        "task_def456",
        {"workspace_job_id": "job_2"},
        _job_id="task_def456",
    )
    assert result["status"] == "queued"
    assert result["delivery"] == "worker"
    assert result["result"] == {}


@pytest.mark.asyncio
async def test_poll_task_result_unwraps_worker_envelope() -> None:
    with patch(
        "app.services.task_runner.bridge.read_task_result",
        new=AsyncMock(
            return_value={
                "task_id": "task_def456",
                "task_name": "babel.prepare_pdbqt",
                "status": "completed",
                "result": {"is_valid": True, "rotatable_bonds": 2},
                "task_context": {"workspace_job_id": "job_2"},
                "delivery": "worker",
                "fallback_reason": "",
            }
        ),
    ), \
         patch("app.services.task_runner.bridge.delete_task_result", new=AsyncMock()) as delete_mock:
        result = await poll_task_result(
            "task_def456",
            task_name="babel.prepare_pdbqt",
            task_context={"workspace_job_id": "job_2"},
        )

    delete_mock.assert_awaited_once_with("task_def456")
    assert result is not None
    assert result["delivery"] == "worker"
    assert result["result"]["rotatable_bonds"] == 2


@pytest.mark.asyncio
async def test_run_via_worker_waits_for_result_after_submit() -> None:
    with patch(
        "app.services.task_runner.bridge.submit_task_to_worker",
        new=AsyncMock(
            return_value={
                "task_id": "task_xyz",
                "task_name": "babel.prepare_pdbqt",
                "status": "queued",
                "result": {},
                "task_context": {"workspace_job_id": "job_3"},
                "delivery": "worker",
                "fallback_reason": "",
            }
        ),
    ), \
         patch(
             "app.services.task_runner.bridge.wait_for_task_result",
             new=AsyncMock(
                 return_value={
                     "task_id": "task_xyz",
                     "task_name": "babel.prepare_pdbqt",
                     "status": "completed",
                     "result": {"is_valid": True, "rotatable_bonds": 2},
                     "task_context": {"workspace_job_id": "job_3"},
                     "delivery": "worker",
                     "fallback_reason": "",
                 }
             ),
         ):
        result = await run_via_worker(
            "babel.prepare_pdbqt",
            {"smiles": "CCO"},
            task_context={"workspace_job_id": "job_3"},
            return_envelope=True,
        )

    assert result["status"] == "completed"
    assert result["result"]["rotatable_bonds"] == 2


@pytest.mark.asyncio
async def test_wait_for_task_result_falls_back_to_direct_on_timeout() -> None:
    fake_pool = SimpleNamespace(abort_job=AsyncMock())
    with patch("app.services.task_runner.bridge.get_arq_pool", new=AsyncMock(return_value=fake_pool)), \
         patch("app.services.task_runner.bridge.get_poll_interval_seconds", return_value=0.001), \
         patch("app.services.task_runner.bridge.poll_task_result", new=AsyncMock(return_value=None)), \
         patch("app.services.task_runner.bridge._run_direct", new=AsyncMock(return_value={"is_valid": True, "smiles": "CCO"})):
        result = await wait_for_task_result(
            "task_timeout",
            task_name="babel.build_3d_conformer",
            kwargs={"smiles": "CCO"},
            task_context={"workspace_job_id": "job_timeout"},
            timeout=0.01,
        )

    fake_pool.abort_job.assert_awaited_once_with("task_timeout")
    assert result["delivery"] == "direct"
    assert result["fallback_reason"] == "timeout"
    assert result["result"]["smiles"] == "CCO"


@pytest.mark.asyncio
async def test_run_chem_task_embeds_task_context_in_worker_envelope() -> None:
    with patch(
        "app.services.task_runner.worker._execute_task",
        new=AsyncMock(return_value={"is_valid": True, "download_id": "task_1"}),
    ), \
         patch("app.services.task_runner.worker.store_task_result", new=AsyncMock()) as store_mock:
        result = await run_chem_task(
            {},
            "babel.prepare_pdbqt",
            {"smiles": "CCO"},
            "task_1",
            {"workspace_job_id": "job_4", "workspace_target_handle": "root_molecule"},
        )

    assert result["task_context"]["workspace_job_id"] == "job_4"
    assert result["result"]["download_id"] == "task_1"
    store_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_3d_conformer_postprocessor_routes_through_worker_with_workspace_context() -> None:
    artifacts: list[dict] = []
    dispatch_mock = AsyncMock()
    bridge_mock = AsyncMock(
        return_value={
            "is_valid": True,
            "smiles": "CCO",
            "name": "ethanol",
            "sdf_content": "mock-sdf",
            "energy_kcal_mol": -7.2,
        }
    )

    with patch("app.agents.postprocessors.run_via_worker", new=bridge_mock), \
         patch("app.agents.postprocessors.adispatch_custom_event", new=dispatch_mock):
        result = await postprocess_build_3d_conformer(
            {"is_valid": True, "smiles": "CCO", "name": "ethanol"},
            {"smiles": "CCO", "name": "ethanol", "forcefield": "mmff94", "steps": 500},
            artifacts,
            {
                "configurable": {
                    "thread_id": "project-1",
                    "project_id": "project-1",
                    "workspace_id": "ws_1",
                    "workspace_version": 3,
                    "workspace_job_id": "job_123",
                    "workspace_target_handle": "root_molecule",
                }
            },
        )

    bridge_mock.assert_awaited_once_with(
        "babel.build_3d_conformer",
        {"smiles": "CCO", "name": "ethanol", "forcefield": "mmff94", "steps": 500},
        timeout=120.0,
        task_context={
            "thread_id": "project-1",
            "project_id": "project-1",
            "workspace_id": "ws_1",
            "workspace_version": 3,
            "workspace_job_id": "job_123",
            "workspace_target_handle": "root_molecule",
        },
    )
    assert artifacts and artifacts[0]["kind"] == "conformer_sdf"
    assert result["message"] == "3D构象已生成，SDF 文件已发送给用户"
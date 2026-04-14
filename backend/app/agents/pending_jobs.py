from __future__ import annotations

from typing import Any, cast

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

from app.agents.postprocessors import finalize_async_tool_result
from app.agents.utils import tool_result_to_text
from app.domain.schemas.agent import ChemState, PendingWorkerTask
from app.services.task_runner.bridge import poll_task_result
from app.services.workspace import complete_workspace_job, ensure_workspace_projection, extract_workspace_job_result


async def drain_pending_worker_tasks(
    state: ChemState,
    config: RunnableConfig,
) -> dict[str, Any]:
    pending_tasks = [
        cast(PendingWorkerTask, dict(task))
        for task in state.get("pending_worker_tasks", [])
        if isinstance(task, dict)
    ]
    if not pending_tasks:
        return {
            "messages": [],
            "artifacts": [],
            "workspace_events": [],
            "workspace_projection": dict(state.get("workspace_projection") or {}),
            "pending_worker_tasks": [],
            "tool_events": [],
        }

    cfg = (config or {}).get("configurable") or {}
    workspace_projection = ensure_workspace_projection(
        state,
        project_id=str(cfg.get("thread_id") or "default_project"),
    )
    drained_messages: list[ToolMessage] = []
    artifacts: list[dict] = []
    workspace_events: list[dict] = []
    remaining_tasks: list[PendingWorkerTask] = []
    tool_events: list[dict[str, Any]] = []

    for pending in pending_tasks:
        task_id = str(pending.get("task_id") or "").strip()
        tool_name = str(pending.get("tool_name") or "").strip()
        if not task_id or not tool_name:
            continue

        envelope = await poll_task_result(
            task_id,
            task_name=str(pending.get("task_name") or ""),
            task_context={
                key: pending[key]
                for key in ("workspace_job_id", "workspace_target_handle", "project_id", "workspace_id", "workspace_version")
                if key in pending
            },
        )
        if envelope is None:
            remaining_tasks.append(pending)
            continue

        finalized = await finalize_async_tool_result(
            tool_name,
            dict(envelope.get("result") or {}),
            artifacts,
            config,
        )
        job_result = extract_workspace_job_result(tool_name, finalized, artifacts)
        workspace_projection, new_workspace_events = complete_workspace_job(
            workspace_projection,
            job_id=str(pending.get("workspace_job_id") or ""),
            diagnostics=job_result["diagnostics"],
            artifact_id=job_result["artifact_id"],
            hover_text=job_result["hover_text"],
            result_summary=job_result["result_summary"],
        )
        workspace_events.extend(new_workspace_events)
        drained_messages.append(
            ToolMessage(
                content=tool_result_to_text(finalized),
                tool_call_id=task_id,
                name=tool_name,
            )
        )
        tool_events.append({
            "tool_name": tool_name,
            "task_id": task_id,
            "output": finalized,
        })

    return {
        "messages": drained_messages,
        "artifacts": artifacts,
        "workspace_events": workspace_events,
        "workspace_projection": workspace_projection.model_dump(),
        "pending_worker_tasks": remaining_tasks,
        "tool_events": tool_events,
    }
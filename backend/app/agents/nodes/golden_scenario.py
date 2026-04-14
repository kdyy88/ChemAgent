from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.agents.utils import dispatch_task_update, sanitize_messages_for_state
from app.domain.schemas.agent import ChemState, PendingWorkerTask, Task
from app.services.task_runner.bridge import submit_task_to_worker
from app.services.workspace import (
    CandidateSpec,
    compute_workspace_delta,
    initialize_scaffold_hop_session,
    launch_candidate_conformer_jobs,
    register_scaffold_hop_rules,
    create_three_candidates,
)
from app.services.workspace.applicator import WorkspaceApplicator


IBRUTINIB_SMILES = "CC1=C(C(=CC=C1)NC(=O)C=C)N2CC[C@H](C2)OCC=CC#N"
MVP_CANDIDATES = [
    CandidateSpec(smiles="C=CC(=O)N1CCC(CC1)Oc2nccc3cc4ccccc4[nH]c23", display_name="Candidate 1"),
    CandidateSpec(smiles="C=CC(=O)N1CCC(CC1)Oc2nc3ccccc3[nH]c2C", display_name="Candidate 2"),
    CandidateSpec(smiles="C=CC(=O)N1CCC(CC1)Oc2nccc3c2[nH]cc3c4ccccc4", display_name="Candidate 3"),
]


_DELTA_EVENT_TYPE = {
    "node_upsert": "molecule.upserted",
    "relation_upsert": "relation.upserted",
    "viewport_set": "viewport.changed",
    "rule_add": "rules.updated",
    "job_upsert": "job.started",
    "job_progress": "job.progress",
    "job_stale": "job.stale",
    "job_complete": "job.completed",
}


def route_from_planner(state: ChemState) -> str:
    return "golden_scenario" if state.get("scenario_kind") == "scaffold_hop_mvp" else "chem_agent"


async def golden_scenario_node(state: ChemState, config: RunnableConfig) -> dict:
    previous_workspace_raw = state.get("workspace_projection")
    previous_workspace = None
    if previous_workspace_raw:
        try:
            from app.domain.schemas.workspace import WorkspaceProjection  # noqa: PLC0415

            previous_workspace = (
                previous_workspace_raw
                if isinstance(previous_workspace_raw, WorkspaceProjection)
                else WorkspaceProjection.model_validate(previous_workspace_raw)
            )
        except Exception:
            previous_workspace = None

    tasks: list[Task] = [dict(task) for task in state.get("tasks", [])]
    project_id = str(((config or {}).get("configurable") or {}).get("thread_id") or "default_project")

    workspace = initialize_scaffold_hop_session(
        project_id=project_id,
        parent_smiles=IBRUTINIB_SMILES,
        parent_name="Ibrutinib",
    )
    tasks[0]["status"] = "completed"
    await dispatch_task_update(tasks, config, source="golden_scenario")

    workspace = register_scaffold_hop_rules(workspace)
    tasks[1]["status"] = "completed"
    await dispatch_task_update(tasks, config, source="golden_scenario")

    workspace = create_three_candidates(workspace, MVP_CANDIDATES)
    tasks[2]["status"] = "completed"
    tasks[3]["status"] = "completed"
    await dispatch_task_update(tasks, config, source="golden_scenario")

    job_ids = [f"job_candidate_{index}_conf" for index in range(1, 4)]
    workspace = launch_candidate_conformer_jobs(
        workspace,
        job_ids=job_ids,
        forcefield="mmff94",
        steps=500,
        approval_state="not_required",
    )

    pending_worker_tasks: list[PendingWorkerTask] = []
    for handle, job_id in zip(workspace.candidate_handles, job_ids, strict=True):
        submission = await submit_task_to_worker(
            "babel.build_3d_conformer",
            {
                "smiles": workspace.nodes[workspace.handle_bindings[handle].node_id].canonical_smiles,
                "name": workspace.nodes[workspace.handle_bindings[handle].node_id].display_name or handle,
                "forcefield": "mmff94",
                "steps": 500,
            },
            task_context={
                "workspace_job_id": job_id,
                "workspace_target_handle": handle,
                "workspace_id": workspace.workspace_id,
                "project_id": workspace.project_id,
                "workspace_version": workspace.version,
            },
        )
        if submission.get("status") == "queued":
            pending_worker_tasks.append(
                {
                    "task_id": str(submission["task_id"]),
                    "task_name": "babel.build_3d_conformer",
                    "tool_name": "tool_build_3d_conformer",
                    "workspace_job_id": job_id,
                    "workspace_target_handle": handle,
                    "project_id": workspace.project_id,
                    "workspace_id": workspace.workspace_id,
                    "workspace_version": workspace.version,
                }
            )

    tasks[4]["status"] = "completed"
    await dispatch_task_update(tasks, config, source="golden_scenario")

    baseline_workspace = previous_workspace or WorkspaceApplicator.create(project_id=project_id)
    delta = compute_workspace_delta(baseline_workspace, workspace)
    workspace_events = [
        {"type": "workspace.snapshot", "workspace": workspace.model_dump(), "version": workspace.version},
        {"type": "workspace.delta", "delta": delta.model_dump(), "version": workspace.version},
        *[
            {"type": _DELTA_EVENT_TYPE.get(op.kind, "workspace.delta"), **op.payload, "version": workspace.version}
            for op in delta.ops
        ],
        *[
            {
                "type": "job.started",
                "job_id": job_id,
                "job_type": "conformer3d",
                "target_handle": handle,
                "version": workspace.version,
            }
            for handle, job_id in zip(workspace.candidate_handles, job_ids, strict=True)
        ],
    ]

    summary = (
        "Golden-path MVP workflow started: created the ibrutinib root, registered scaffold-hop rules, "
        "generated 3 fused-indole candidates, focused a single comparison viewport, and launched 3 conformer jobs."
    )
    messages = await sanitize_messages_for_state([AIMessage(content=summary)], source="golden_scenario")

    return {
        "messages": messages,
        "tasks": tasks,
        "scenario_kind": "scaffold_hop_mvp",
        "candidate_generation_status": "launched",
        "active_handle": "root_molecule",
        "candidate_handles": list(workspace.candidate_handles),
        "last_workspace_version": workspace.version,
        "workspace_projection": workspace,
        "workspace_delta": delta.model_dump(),
        "workspace_events": workspace_events,
        "pending_worker_tasks": pending_worker_tasks,
        "pending_approval_job_ids": [],
    }
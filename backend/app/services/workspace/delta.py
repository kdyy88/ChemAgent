from __future__ import annotations

from app.domain.schemas.workspace import WorkspaceDelta, WorkspaceDeltaOp, WorkspaceProjection


def compute_workspace_delta(before: WorkspaceProjection, after: WorkspaceProjection) -> WorkspaceDelta:
    ops: list[WorkspaceDeltaOp] = []
    scope = "workspace"

    before_nodes = before.nodes
    after_nodes = after.nodes
    for node_id, node in after_nodes.items():
        if node_id not in before_nodes or before_nodes[node_id] != node:
            ops.append(
                WorkspaceDeltaOp(
                    kind="node_upsert",
                    key=node_id,
                    payload={
                        "node_id": node.node_id,
                        "handle": node.handle,
                        "status": node.status,
                    },
                )
            )
            scope = "graph"

    before_relations = before.relations
    for relation_id, relation in after.relations.items():
        if relation_id not in before_relations or before_relations[relation_id] != relation:
            ops.append(
                WorkspaceDeltaOp(
                    kind="relation_upsert",
                    key=relation_id,
                    payload={
                        "relation_id": relation.relation_id,
                        "source_node_id": relation.source_node_id,
                        "target_node_id": relation.target_node_id,
                        "relation_kind": relation.relation_kind,
                    },
                )
            )
            scope = "graph"

    if before.viewport != after.viewport:
        ops.append(
            WorkspaceDeltaOp(
                kind="viewport_set",
                key=after.active_view_id or "active_view",
                payload={
                    "focused_handles": list(after.viewport.focused_handles),
                    "reference_handle": after.viewport.reference_handle,
                },
            )
        )
        scope = "viewport" if scope == "workspace" else scope

    before_rule_ids = {rule.rule_id for rule in before.rules}
    for rule in after.rules:
        if rule.rule_id not in before_rule_ids:
            ops.append(
                WorkspaceDeltaOp(
                    kind="rule_add",
                    key=rule.rule_id,
                    payload={
                        "rule_id": rule.rule_id,
                        "kind": rule.kind,
                        "text": rule.text,
                    },
                )
            )
            scope = "rules" if scope == "workspace" else scope

    before_jobs = before.async_jobs
    for job_id, job in after.async_jobs.items():
        previous_job = before_jobs.get(job_id)
        if previous_job is None:
            op_kind = "job_upsert"
        elif previous_job.status != job.status:
            if job.status == "stale":
                op_kind = "job_stale"
            elif job.status == "completed":
                op_kind = "job_complete"
            else:
                op_kind = "job_progress"
        elif previous_job != job:
            op_kind = "job_progress"
        else:
            continue

        ops.append(
            WorkspaceDeltaOp(
                kind=op_kind,
                key=job_id,
                payload={
                    "job_id": job.job_id,
                    "job_type": job.job_type,
                    "target_handle": job.target_handle,
                    "status": job.status,
                    "artifact_id": job.artifact_id,
                    "stale_reason": job.stale_reason,
                },
            )
        )
        scope = "jobs" if scope == "workspace" else scope

    return WorkspaceDelta(
        previous_version=before.version,
        version=after.version,
        scope=scope,
        ops=ops,
    )
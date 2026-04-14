from __future__ import annotations

from typing import Any

from app.domain.schemas.workspace import (
    ApplyAsyncJobResultCommand,
    CreateCandidateBranchCommand,
    CreateRootMoleculeCommand,
    PatchNodeCommand,
    RegisterRuleCommand,
    SetViewportCommand,
    StartAsyncJobCommand,
    WorkspaceProjection,
)
from app.services.workspace.applicator import (
    UnknownWorkspaceHandleError,
    WorkspaceApplicator,
    WorkspaceConflictError,
)


def ensure_workspace_projection(state: dict[str, Any], *, project_id: str) -> WorkspaceProjection:
    raw = state.get("workspace_projection")
    if isinstance(raw, WorkspaceProjection):
        return raw
    if isinstance(raw, dict):
        try:
            return WorkspaceProjection.model_validate(raw)
        except Exception:
            pass

    workspace = WorkspaceApplicator.create(project_id=project_id)
    scratchpad = dict(state.get("scratchpad") or {})
    for rule_text in list(scratchpad.get("established_rules") or []):
        normalized = str(rule_text or "").strip()
        if normalized:
            workspace = WorkspaceApplicator.register_rule(
                workspace,
                RegisterRuleCommand(kind="note", text=normalized, source="legacy_scratchpad", created_by="system"),
            )
    return workspace


def _artifact_to_handle(workspace: WorkspaceProjection, artifact_id: str) -> str | None:
    normalized = str(artifact_id or "").strip()
    if not normalized:
        return None

    for handle, binding in workspace.handle_bindings.items():
        node = workspace.nodes.get(binding.node_id)
        if node is None:
            continue
        if node.node_id == normalized or normalized in node.artifact_ids:
            return handle
    return None


def _next_candidate_handle(workspace: WorkspaceProjection) -> str:
    index = 1
    while True:
        handle = f"candidate_{index}"
        if handle not in workspace.handle_bindings:
            return handle
        index += 1


def _workspace_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": event_type, **payload}


def resolve_workspace_target(
    workspace: WorkspaceProjection,
    *,
    artifact_id: str = "",
    smiles: str = "",
    fallback_smiles: str = "",
) -> tuple[str, str] | None:
    resolved_handle = _artifact_to_handle(workspace, artifact_id)
    if resolved_handle is not None:
        binding = workspace.handle_bindings[resolved_handle]
        return resolved_handle, binding.node_id

    normalized_smiles = str(smiles or fallback_smiles or "").strip()
    if not normalized_smiles:
        return None

    for handle, binding in workspace.handle_bindings.items():
        node = workspace.nodes.get(binding.node_id)
        if node is None:
            continue
        if node.canonical_smiles == normalized_smiles:
            return handle, binding.node_id
    return None


def start_workspace_job(
    workspace: WorkspaceProjection,
    *,
    job_id: str,
    job_type: str,
    target_handle: str,
) -> tuple[WorkspaceProjection, list[dict[str, Any]]]:
    updated = WorkspaceApplicator.start_async_job(
        workspace,
        StartAsyncJobCommand(job_id=job_id, job_type=job_type, target_handle=target_handle),
    )
    return updated, [
        _workspace_event(
            "job.started",
            {
                "job_id": job_id,
                "job_type": job_type,
                "target_handle": target_handle,
                "version": updated.version,
            },
        ),
        _workspace_event("workspace.delta", {"scope": "jobs", "version": updated.version, "job_id": job_id}),
    ]


def complete_workspace_job(
    workspace: WorkspaceProjection,
    *,
    job_id: str,
    diagnostics: dict[str, Any],
    artifact_id: str | None = None,
    hover_text: str = "",
    result_summary: str = "",
) -> tuple[WorkspaceProjection, list[dict[str, Any]]]:
    updated = WorkspaceApplicator.apply_async_job_result(
        workspace,
        ApplyAsyncJobResultCommand(
            job_id=job_id,
            diagnostics=diagnostics,
            artifact_id=artifact_id,
            hover_text=hover_text,
            result_summary=result_summary,
        ),
    )
    job = updated.async_jobs[job_id]
    event_type = "job.completed" if job.status == "completed" else "job.failed"
    payload: dict[str, Any] = {
        "job_id": job_id,
        "status": job.status,
        "target_handle": job.target_handle,
        "artifact_id": artifact_id,
        "summary": result_summary,
        "version": updated.version,
    }
    if job.stale_reason:
        payload["stale_reason"] = job.stale_reason
    return updated, [
        _workspace_event(event_type, payload),
        _workspace_event("workspace.delta", {"scope": "jobs", "version": updated.version, "job_id": job_id, "status": job.status}),
    ]


def extract_workspace_job_result(
    tool_name: str,
    parsed: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_id: str | None = None
    newest_artifact = artifacts[-1] if artifacts else None
    if isinstance(newest_artifact, dict):
        artifact_id = str(newest_artifact.get("artifact_id") or "").strip() or None

    diagnostics: dict[str, Any] = {}
    hover_text = str(parsed.get("message") or "").strip()
    result_summary = hover_text

    if tool_name == "tool_build_3d_conformer":
        diagnostics["conformer_status"] = "ready" if parsed.get("is_valid", True) else "failed"
        if parsed.get("energy_kcal_mol") is not None:
            diagnostics["energy_kcal_mol"] = parsed.get("energy_kcal_mol")
    elif tool_name == "tool_prepare_pdbqt":
        diagnostics["pdbqt_status"] = "ready" if parsed.get("is_valid", True) else "failed"
        if parsed.get("rotatable_bonds") is not None:
            diagnostics["rotatable_bonds"] = parsed.get("rotatable_bonds")

    return {
        "diagnostics": diagnostics,
        "artifact_id": artifact_id,
        "hover_text": hover_text,
        "result_summary": result_summary,
    }


def apply_protocol_to_workspace(
    workspace: WorkspaceProjection,
    protocol_type: str,
    parsed: dict[str, Any],
) -> tuple[WorkspaceProjection, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []

    if protocol_type == "ScratchpadUpdate":
        updated = workspace
        for rule_text in list(parsed.get("established_rules") or []):
            normalized = str(rule_text or "").strip()
            if not normalized:
                continue
            updated = WorkspaceApplicator.register_rule(
                updated,
                RegisterRuleCommand(kind="note", text=normalized, source="tool_protocol", created_by="agent"),
            )
        research_goal = str(parsed.get("research_goal") or "").strip()
        if research_goal:
            updated = WorkspaceApplicator.register_rule(
                updated,
                RegisterRuleCommand(kind="note", text=f"Research goal: {research_goal}", source="tool_protocol", created_by="agent"),
            )
        if updated is workspace:
            return workspace, events
        events.append(_workspace_event("rules.updated", {"count": len(updated.rules), "version": updated.version}))
        events.append(_workspace_event("workspace.delta", {"scope": "rules", "version": updated.version}))
        return updated, events

    if protocol_type == "NodeCreate":
        artifact_id = str(parsed.get("artifact_id") or "").strip()
        smiles = str(parsed.get("smiles") or "").strip()
        parent_artifact_id = str(parsed.get("parent_id") or "").strip()
        aliases = [str(alias).strip() for alias in list(parsed.get("aliases") or []) if str(alias).strip()]
        display_name = aliases[0] if aliases else ""
        diagnostics = dict(parsed.get("diagnostics") or {})
        hover_text = display_name or smiles

        try:
            if not workspace.handle_bindings and not parent_artifact_id:
                updated = WorkspaceApplicator.create_root_molecule(
                    workspace,
                    CreateRootMoleculeCommand(
                        canonical_smiles=smiles,
                        display_name=display_name,
                        node_id=artifact_id or None,
                        artifact_ids=[artifact_id] if artifact_id else [],
                        diagnostics=diagnostics,
                        hover_text=hover_text,
                    ),
                )
            else:
                parent_handle = _artifact_to_handle(workspace, parent_artifact_id)
                if parent_handle is None:
                    raise UnknownWorkspaceHandleError(parent_artifact_id)
                updated = WorkspaceApplicator.create_candidate_branch(
                    workspace,
                    CreateCandidateBranchCommand(
                        parent_handle=parent_handle,
                        handle=_next_candidate_handle(workspace),
                        canonical_smiles=smiles,
                        display_name=display_name,
                        origin=str(parsed.get("creation_operation") or "derived_from_parent"),
                        node_id=artifact_id or None,
                        artifact_ids=[artifact_id] if artifact_id else [],
                        diagnostics=diagnostics,
                        hover_text=hover_text,
                    ),
                )
        except (UnknownWorkspaceHandleError, WorkspaceConflictError) as exc:
            events.append(_workspace_event("workspace.delta", {"scope": "graph", "status": "rejected", "reason": str(exc)}))
            return workspace, events

        created_node = next(
            (node for node in updated.nodes.values() if node.node_id == (artifact_id or "") or node.canonical_smiles == smiles),
            None,
        )
        if created_node is not None:
            events.append(_workspace_event("molecule.upserted", {"node_id": created_node.node_id, "handle": created_node.handle, "version": updated.version}))
            if created_node.parent_node_id:
                events.append(_workspace_event("relation.upserted", {"target_node_id": created_node.node_id, "parent_node_id": created_node.parent_node_id, "version": updated.version}))
        events.append(_workspace_event("viewport.changed", {"focused_handles": list(updated.viewport.focused_handles), "reference_handle": updated.viewport.reference_handle, "version": updated.version}))
        events.append(_workspace_event("workspace.delta", {"scope": "graph", "version": updated.version}))
        return updated, events

    if protocol_type == "BatchNodeUpdate":
        updated = workspace
        changed_nodes: list[str] = []
        for item in list(parsed.get("updates") or []):
            artifact_id = str(item.get("artifact_id") or "").strip()
            handle = _artifact_to_handle(updated, artifact_id)
            if handle is None:
                continue
            node_id = updated.handle_bindings[handle].node_id
            updated = WorkspaceApplicator.patch_node(
                updated,
                PatchNodeCommand(
                    node_id=node_id,
                    diagnostics=dict(item.get("diagnostics") or {}),
                    status=item.get("status"),
                    artifact_id=artifact_id or None,
                ),
            )
            changed_nodes.append(node_id)

        for node_id in changed_nodes:
            node = updated.nodes[node_id]
            events.append(_workspace_event("molecule.upserted", {"node_id": node.node_id, "handle": node.handle, "version": updated.version}))
        if changed_nodes:
            events.append(_workspace_event("workspace.delta", {"scope": "graph", "version": updated.version, "node_count": len(changed_nodes)}))
        return updated, events

    if protocol_type == "ViewportUpdate":
        handles = [
            handle
            for artifact_id in list(parsed.get("focused_artifact_ids") or [])
            if (handle := _artifact_to_handle(workspace, str(artifact_id or "").strip())) is not None
        ]
        if not handles:
            return workspace, events

        reference_artifact_id = str(parsed.get("reference_artifact_id") or "").strip()
        reference_handle = _artifact_to_handle(workspace, reference_artifact_id) if reference_artifact_id else None
        updated = WorkspaceApplicator.set_viewport(
            workspace,
            SetViewportCommand(focused_handles=handles, reference_handle=reference_handle),
        )
        events.append(_workspace_event("viewport.changed", {"focused_handles": list(updated.viewport.focused_handles), "reference_handle": updated.viewport.reference_handle, "version": updated.version}))
        events.append(_workspace_event("workspace.delta", {"scope": "viewport", "version": updated.version}))
        return updated, events

    return workspace, events
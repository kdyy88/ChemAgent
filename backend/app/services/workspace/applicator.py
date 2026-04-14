from __future__ import annotations

from typing import Any

from app.domain.schemas.workspace import (
    ApplyAsyncJobResultCommand,
    AsyncJobPointer,
    CreateCandidateBranchCommand,
    CreateRootMoleculeCommand,
    MarkAsyncJobProgressCommand,
    MarkAsyncJobStaleCommand,
    MoleculeNodeRecord,
    MoleculeRelationRecord,
    PatchNodeCommand,
    RegisterRuleCommand,
    RuleSetEntry,
    SemanticHandleBinding,
    SetViewportCommand,
    StartAsyncJobCommand,
    WorkspaceProjection,
)


class WorkspaceConflictError(ValueError):
    pass


class UnknownWorkspaceHandleError(KeyError):
    pass


class WorkspaceApplicator:
    """Apply validated workspace mutations while guarding against stale state."""

    @staticmethod
    def create(project_id: str, workspace_id: str | None = None) -> WorkspaceProjection:
        if workspace_id is None:
            return WorkspaceProjection(project_id=project_id)
        return WorkspaceProjection(project_id=project_id, workspace_id=workspace_id)

    @classmethod
    def initialize_scaffold_hop_workspace(
        cls,
        workspace: WorkspaceProjection,
        command: CreateRootMoleculeCommand,
    ) -> WorkspaceProjection:
        updated = cls.create_root_molecule(workspace, command)
        return updated.model_copy(
            update={
                "scenario_kind": "scaffold_hop_mvp",
                "active_view_id": "active_view",
            },
            deep=True,
        )

    @staticmethod
    def _bump_version(workspace: WorkspaceProjection) -> WorkspaceProjection:
        return workspace.model_copy(update={"version": workspace.version + 1}, deep=True)

    @staticmethod
    def _resolve_handle(workspace: WorkspaceProjection, handle: str) -> SemanticHandleBinding:
        binding = workspace.handle_bindings.get(handle)
        if binding is None:
            raise UnknownWorkspaceHandleError(f"Unknown workspace handle: {handle}")
        return binding

    @staticmethod
    def _ensure_handle_available(workspace: WorkspaceProjection, handle: str) -> None:
        if handle in workspace.handle_bindings:
            raise WorkspaceConflictError(f"Workspace handle already exists: {handle}")

    @classmethod
    def create_root_molecule(
        cls,
        workspace: WorkspaceProjection,
        command: CreateRootMoleculeCommand,
    ) -> WorkspaceProjection:
        cls._ensure_handle_available(workspace, command.handle)
        updated = cls._bump_version(workspace)
        node = MoleculeNodeRecord(
            node_id=command.node_id or MoleculeNodeRecord.model_fields["node_id"].default_factory(),
            handle=command.handle,
            canonical_smiles=command.canonical_smiles,
            display_name=command.display_name,
            status="active",
            diagnostics=dict(command.diagnostics),
            artifact_ids=list(dict.fromkeys(command.artifact_ids)),
            hover_text=command.hover_text,
            origin="root_commit",
        )
        updated.nodes[node.node_id] = node
        updated.handle_bindings[command.handle] = SemanticHandleBinding(
            handle=command.handle,
            node_id=node.node_id,
            bound_at_version=updated.version,
        )
        updated.viewport.focused_handles = [command.handle]
        updated.viewport.reference_handle = command.handle
        if updated.root_handle is None:
            updated.root_handle = command.handle
        if updated.active_view_id is None:
            updated.active_view_id = "active_view"
        return updated

    @classmethod
    def register_rule(
        cls,
        workspace: WorkspaceProjection,
        command: RegisterRuleCommand,
    ) -> WorkspaceProjection:
        updated = cls._bump_version(workspace)
        updated.rules.append(
            RuleSetEntry(
                kind=command.kind,
                text=command.text,
                normalized_value=command.normalized_value,
                source=command.source,
                created_by=command.created_by,
            )
        )
        return updated

    @classmethod
    def create_candidate_branch(
        cls,
        workspace: WorkspaceProjection,
        command: CreateCandidateBranchCommand,
    ) -> WorkspaceProjection:
        parent_binding = cls._resolve_handle(workspace, command.parent_handle)
        cls._ensure_handle_available(workspace, command.handle)

        updated = cls._bump_version(workspace)
        node = MoleculeNodeRecord(
            node_id=command.node_id or MoleculeNodeRecord.model_fields["node_id"].default_factory(),
            handle=command.handle,
            canonical_smiles=command.canonical_smiles,
            display_name=command.display_name,
            parent_node_id=parent_binding.node_id,
            origin=command.origin,
            status="candidate",
            diagnostics=dict(command.diagnostics),
            artifact_ids=list(dict.fromkeys(command.artifact_ids)),
            hover_text=command.hover_text,
        )
        relation = MoleculeRelationRecord(
            source_node_id=parent_binding.node_id,
            target_node_id=node.node_id,
            label=command.origin,
        )
        updated.nodes[node.node_id] = node
        updated.relations[relation.relation_id] = relation
        updated.handle_bindings[command.handle] = SemanticHandleBinding(
            handle=command.handle,
            node_id=node.node_id,
            bound_at_version=updated.version,
        )
        if command.handle not in updated.candidate_handles:
            updated.candidate_handles.append(command.handle)
        if command.parent_handle not in updated.viewport.focused_handles:
            updated.viewport.focused_handles.append(command.parent_handle)
        if command.handle not in updated.viewport.focused_handles:
            updated.viewport.focused_handles.append(command.handle)
        if updated.viewport.reference_handle is None:
            updated.viewport.reference_handle = command.parent_handle
        return updated

    @classmethod
    def create_candidate_batch(
        cls,
        workspace: WorkspaceProjection,
        commands: list[CreateCandidateBranchCommand],
    ) -> WorkspaceProjection:
        updated = workspace
        for command in commands:
            updated = cls.create_candidate_branch(updated, command)
        return updated

    @classmethod
    def set_viewport(
        cls,
        workspace: WorkspaceProjection,
        command: SetViewportCommand,
    ) -> WorkspaceProjection:
        for handle in command.focused_handles:
            cls._resolve_handle(workspace, handle)
        if command.reference_handle is not None:
            cls._resolve_handle(workspace, command.reference_handle)

        updated = cls._bump_version(workspace)
        updated.viewport.focused_handles = list(dict.fromkeys(command.focused_handles))
        updated.viewport.reference_handle = command.reference_handle
        if updated.active_view_id is None:
            updated.active_view_id = "active_view"
        return updated

    @classmethod
    def set_single_comparison_view(
        cls,
        workspace: WorkspaceProjection,
        *,
        root_handle: str,
        candidate_handles: list[str],
    ) -> WorkspaceProjection:
        focused_handles = [root_handle, *candidate_handles]
        return cls.set_viewport(
            workspace,
            SetViewportCommand(
                focused_handles=focused_handles,
                reference_handle=root_handle,
            ),
        )

    @classmethod
    def start_async_job(
        cls,
        workspace: WorkspaceProjection,
        command: StartAsyncJobCommand,
    ) -> WorkspaceProjection:
        if command.job_id in workspace.async_jobs:
            raise WorkspaceConflictError(f"Async job already exists: {command.job_id}")
        target_binding = cls._resolve_handle(workspace, command.target_handle)

        updated = cls._bump_version(workspace)
        updated.async_jobs[command.job_id] = AsyncJobPointer(
            job_id=command.job_id,
            job_type=command.job_type,
            target_handle=command.target_handle,
            target_node_id=target_binding.node_id,
            base_workspace_version=workspace.version,
            requested_at_version=updated.version,
            status="running",
            approval_state=command.approval_state,
            job_args=dict(command.job_args),
        )
        return updated

    @classmethod
    def mark_job_progress(
        cls,
        workspace: WorkspaceProjection,
        command: MarkAsyncJobProgressCommand,
    ) -> WorkspaceProjection:
        job = workspace.async_jobs.get(command.job_id)
        if job is None:
            raise WorkspaceConflictError(f"Unknown async job: {command.job_id}")

        updated = cls._bump_version(workspace)
        updated_job = updated.async_jobs[command.job_id]
        updated.async_jobs[command.job_id] = updated_job.model_copy(
            update={
                "status": "running",
                "result_summary": command.result_summary or updated_job.result_summary,
            }
        )

        if command.diagnostics:
            node = updated.nodes.get(updated_job.target_node_id)
            if node is not None:
                updated.nodes[updated_job.target_node_id] = node.model_copy(
                    update={
                        "diagnostics": {**node.diagnostics, **command.diagnostics},
                    }
                )
        return updated

    @classmethod
    def mark_job_stale(
        cls,
        workspace: WorkspaceProjection,
        command: MarkAsyncJobStaleCommand,
    ) -> WorkspaceProjection:
        job = workspace.async_jobs.get(command.job_id)
        if job is None:
            raise WorkspaceConflictError(f"Unknown async job: {command.job_id}")

        updated = cls._bump_version(workspace)
        updated_job = updated.async_jobs[command.job_id]
        updated.async_jobs[command.job_id] = updated_job.model_copy(
            update={
                "status": "stale",
                "stale_reason": command.stale_reason,
                "result_summary": command.result_summary or updated_job.result_summary,
            }
        )
        return updated

    @classmethod
    def patch_node(
        cls,
        workspace: WorkspaceProjection,
        command: PatchNodeCommand,
    ) -> WorkspaceProjection:
        node = workspace.nodes.get(command.node_id)
        if node is None:
            raise WorkspaceConflictError(f"Unknown workspace node: {command.node_id}")

        updated = cls._bump_version(workspace)
        current_node = updated.nodes[command.node_id]
        merged_diagnostics: dict[str, Any] = {**current_node.diagnostics, **command.diagnostics}
        artifact_ids = list(current_node.artifact_ids)
        if command.artifact_id and command.artifact_id not in artifact_ids:
            artifact_ids.append(command.artifact_id)

        updated.nodes[command.node_id] = current_node.model_copy(
            update={
                "diagnostics": merged_diagnostics,
                "artifact_ids": artifact_ids,
                "status": command.status or current_node.status,
                "hover_text": command.hover_text or current_node.hover_text,
            }
        )
        return updated

    @classmethod
    def apply_async_job_result(
        cls,
        workspace: WorkspaceProjection,
        command: ApplyAsyncJobResultCommand,
    ) -> WorkspaceProjection:
        job = workspace.async_jobs.get(command.job_id)
        if job is None:
            raise WorkspaceConflictError(f"Unknown async job: {command.job_id}")

        current_binding = workspace.handle_bindings.get(job.target_handle)
        updated = cls._bump_version(workspace)
        updated_job = updated.async_jobs[command.job_id]

        if current_binding is None or current_binding.node_id != job.target_node_id:
            updated_job.status = "stale"
            updated_job.stale_reason = "target handle no longer points to the original node"
            updated_job.result_summary = command.result_summary
            return updated

        node = updated.nodes.get(job.target_node_id)
        if node is None or node.status == "archived":
            updated_job.status = "stale"
            updated_job.stale_reason = "target node no longer exists in the active workspace"
            updated_job.result_summary = command.result_summary
            return updated

        merged_diagnostics: dict[str, Any] = {**node.diagnostics, **command.diagnostics}
        artifact_ids = list(node.artifact_ids)
        if command.artifact_id and command.artifact_id not in artifact_ids:
            artifact_ids.append(command.artifact_id)

        updated.nodes[job.target_node_id] = node.model_copy(
            update={
                "diagnostics": merged_diagnostics,
                "artifact_ids": artifact_ids,
                "hover_text": command.hover_text or node.hover_text,
            }
        )
        updated.async_jobs[command.job_id] = updated_job.model_copy(
            update={
                "status": "completed",
                "artifact_id": command.artifact_id,
                "completed_at_version": updated.version,
                "result_summary": command.result_summary,
                "stale_reason": "",
            }
        )
        return updated

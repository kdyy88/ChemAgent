from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.domain.schemas.workspace import (
    CreateCandidateBranchCommand,
    CreateRootMoleculeCommand,
    RegisterRuleCommand,
    StartAsyncJobCommand,
    WorkspaceProjection,
)
from app.services.workspace.applicator import WorkspaceApplicator, WorkspaceConflictError


class CandidateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smiles: str = Field(min_length=1)
    display_name: str = Field(default="")
    origin: str = Field(default="scaffold_hop_mvp")


def initialize_scaffold_hop_session(
    *,
    project_id: str,
    parent_smiles: str,
    parent_name: str = "Ibrutinib",
) -> WorkspaceProjection:
    workspace = WorkspaceApplicator.create(project_id=project_id)
    return WorkspaceApplicator.initialize_scaffold_hop_workspace(
        workspace,
        CreateRootMoleculeCommand(
            canonical_smiles=parent_smiles,
            display_name=parent_name,
            handle="root_molecule",
            hover_text=parent_name,
        ),
    )


def register_scaffold_hop_rules(workspace: WorkspaceProjection) -> WorkspaceProjection:
    updated = workspace
    for command in (
        RegisterRuleCommand(kind="preserve", text="Preserve the acrylamide warhead", normalized_value="acrylamide_warhead"),
        RegisterRuleCommand(kind="require", text="Require a fused indole scaffold", normalized_value="fused_indole"),
        RegisterRuleCommand(kind="target", text="Generate exactly 3 candidate molecules", normalized_value="candidate_count=3"),
    ):
        updated = WorkspaceApplicator.register_rule(updated, command)
    return updated


def create_three_candidates(
    workspace: WorkspaceProjection,
    candidates: Iterable[CandidateSpec],
) -> WorkspaceProjection:
    candidate_list = list(candidates)
    if len(candidate_list) != 3:
        raise WorkspaceConflictError("scaffold_hop_mvp requires exactly 3 candidate molecules")

    updated = workspace
    commands: list[CreateCandidateBranchCommand] = []
    for index, candidate in enumerate(candidate_list, start=1):
        commands.append(
            CreateCandidateBranchCommand(
                parent_handle=updated.root_handle or "root_molecule",
                handle=f"candidate_{index}",
                canonical_smiles=candidate.smiles,
                display_name=candidate.display_name or f"Candidate {index}",
                origin=candidate.origin,
                hover_text=candidate.display_name or f"Candidate {index}",
            )
        )

    updated = WorkspaceApplicator.create_candidate_batch(updated, commands)
    return WorkspaceApplicator.set_single_comparison_view(
        updated,
        root_handle=updated.root_handle or "root_molecule",
        candidate_handles=updated.candidate_handles,
    )


def launch_candidate_conformer_jobs(
    workspace: WorkspaceProjection,
    *,
    job_ids: list[str],
    forcefield: str = "mmff94",
    steps: int = 500,
    approval_state: str = "pending",
) -> WorkspaceProjection:
    if len(job_ids) != len(workspace.candidate_handles):
        raise WorkspaceConflictError("job_ids count must match candidate handle count")

    updated = workspace
    for handle, job_id in zip(workspace.candidate_handles, job_ids, strict=True):
        updated = WorkspaceApplicator.start_async_job(
            updated,
            StartAsyncJobCommand(
                job_id=job_id,
                job_type="conformer3d",
                target_handle=handle,
                approval_state=approval_state,
                job_args={"forcefield": forcefield, "steps": steps},
            ),
        )
    return updated
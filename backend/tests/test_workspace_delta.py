from __future__ import annotations

from app.domain.schemas.workspace import (
    ApplyAsyncJobResultCommand,
    CreateCandidateBranchCommand,
    CreateRootMoleculeCommand,
    StartAsyncJobCommand,
)
from app.services.workspace import WorkspaceApplicator, compute_workspace_delta


def test_root_creation_produces_node_and_viewport_delta() -> None:
    before = WorkspaceApplicator.create(project_id="proj_ibrutinib")
    after = WorkspaceApplicator.initialize_scaffold_hop_workspace(
        before,
        CreateRootMoleculeCommand(
            canonical_smiles="CC1=C(C(=CC=C1)NC(=O)C=C)N2CC[C@H](C2)OCC=CC#N",
            display_name="Ibrutinib",
        ),
    )

    delta = compute_workspace_delta(before, after)

    assert delta.previous_version == 0
    assert delta.version == after.version
    assert any(op.kind == "node_upsert" for op in delta.ops)
    assert any(op.kind == "viewport_set" for op in delta.ops)


def test_candidate_branch_produces_relation_delta() -> None:
    before = WorkspaceApplicator.initialize_scaffold_hop_workspace(
        WorkspaceApplicator.create(project_id="proj_ibrutinib"),
        CreateRootMoleculeCommand(canonical_smiles="CCO", display_name="Root"),
    )
    after = WorkspaceApplicator.create_candidate_branch(
        before,
        CreateCandidateBranchCommand(
            parent_handle="root_molecule",
            handle="candidate_1",
            canonical_smiles="CCN",
            display_name="Candidate 1",
        ),
    )

    delta = compute_workspace_delta(before, after)

    assert any(op.kind == "node_upsert" and op.payload["handle"] == "candidate_1" for op in delta.ops)
    assert any(op.kind == "relation_upsert" for op in delta.ops)


def test_job_status_change_produces_job_complete_delta() -> None:
    before = WorkspaceApplicator.create_root_molecule(
        WorkspaceApplicator.create(project_id="proj_ibrutinib"),
        CreateRootMoleculeCommand(canonical_smiles="CCO"),
    )
    before = WorkspaceApplicator.start_async_job(
        before,
        StartAsyncJobCommand(job_id="job_conf_1", job_type="conformer3d", target_handle="root_molecule"),
    )
    after = WorkspaceApplicator.apply_async_job_result(
        before,
        ApplyAsyncJobResultCommand(
            job_id="job_conf_1",
            diagnostics={"conformer_status": "ready"},
            artifact_id="art_conf_1",
            result_summary="ready",
        ),
    )

    delta = compute_workspace_delta(before, after)

    assert any(op.kind == "job_complete" and op.key == "job_conf_1" for op in delta.ops)
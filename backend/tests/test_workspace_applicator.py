from __future__ import annotations

from app.domain.schemas.workspace import (
    ApplyAsyncJobResultCommand,
    CreateCandidateBranchCommand,
    CreateRootMoleculeCommand,
    MarkAsyncJobProgressCommand,
    MarkAsyncJobStaleCommand,
    RegisterRuleCommand,
    SetViewportCommand,
    StartAsyncJobCommand,
)
from app.services.workspace import (
    UnknownWorkspaceHandleError,
    WorkspaceApplicator,
    complete_workspace_job,
    project_legacy_workspace_view,
)


def test_create_root_and_branch_builds_workspace_projection() -> None:
    workspace = WorkspaceApplicator.create(project_id="proj_ibrutinib")
    workspace = WorkspaceApplicator.initialize_scaffold_hop_workspace(
        workspace,
        CreateRootMoleculeCommand(
            canonical_smiles="CC1=C(C(=CC=C1)NC(=O)C=C)N2CC[C@H](C2)OCC=CC#N",
            display_name="Ibrutinib",
        ),
    )
    workspace = WorkspaceApplicator.register_rule(
        workspace,
        RegisterRuleCommand(kind="preserve", text="必须保留丙烯酰胺 warhead"),
    )
    workspace = WorkspaceApplicator.register_rule(
        workspace,
        RegisterRuleCommand(kind="require", text="必须包含并环吲哚"),
    )
    workspace = WorkspaceApplicator.create_candidate_branch(
        workspace,
        CreateCandidateBranchCommand(
            parent_handle="root_molecule",
            handle="candidate_1",
            canonical_smiles="C=CC(=O)N1CCC(CC1)Oc2nccc3cc4ccccc4[nH]c23",
            display_name="Candidate 1",
            origin="scaffold_hop_fused_indole",
        ),
    )

    assert workspace.viewport.reference_handle == "root_molecule"
    assert workspace.viewport.focused_handles == ["root_molecule", "candidate_1"]
    assert workspace.root_handle == "root_molecule"
    assert workspace.candidate_handles == ["candidate_1"]
    assert workspace.scenario_kind == "scaffold_hop_mvp"
    assert len(workspace.rules) == 2
    assert "candidate_1" in workspace.handle_bindings


def test_project_legacy_workspace_view_uses_projection_as_truth() -> None:
    workspace = WorkspaceApplicator.create(project_id="proj_ibrutinib")
    workspace = WorkspaceApplicator.initialize_scaffold_hop_workspace(
        workspace,
        CreateRootMoleculeCommand(canonical_smiles="CCO", display_name="Seed"),
    )
    workspace = WorkspaceApplicator.create_candidate_branch(
        workspace,
        CreateCandidateBranchCommand(
            parent_handle="root_molecule",
            handle="candidate_1",
            canonical_smiles="CCN",
            display_name="Child",
            origin="scaffold_hop",
        ),
    )

    viewport, molecule_tree = project_legacy_workspace_view(workspace)

    root_binding = workspace.handle_bindings["root_molecule"]
    child_binding = workspace.handle_bindings["candidate_1"]
    root_node = workspace.nodes[root_binding.node_id]
    child_node = workspace.nodes[child_binding.node_id]

    assert viewport["focused_artifact_ids"] == [root_node.node_id, child_node.node_id]
    assert viewport["reference_artifact_id"] == root_node.node_id
    assert molecule_tree[root_node.node_id]["smiles"] == "CCO"
    assert molecule_tree[child_node.node_id]["parent_id"] == root_node.node_id


def test_unknown_parent_handle_is_rejected() -> None:
    workspace = WorkspaceApplicator.create(project_id="proj_ibrutinib")

    try:
        WorkspaceApplicator.create_candidate_branch(
            workspace,
            CreateCandidateBranchCommand(
                parent_handle="hallucinated_root",
                handle="candidate_1",
                canonical_smiles="CCO",
            ),
        )
    except UnknownWorkspaceHandleError as exc:
        assert "hallucinated_root" in str(exc)
    else:
        raise AssertionError("Expected UnknownWorkspaceHandleError")


def test_async_job_result_is_marked_stale_when_handle_binding_changes() -> None:
    workspace = WorkspaceApplicator.create(project_id="proj_ibrutinib")
    workspace = WorkspaceApplicator.create_root_molecule(
        workspace,
        CreateRootMoleculeCommand(canonical_smiles="CCO"),
    )
    workspace = WorkspaceApplicator.start_async_job(
        workspace,
        StartAsyncJobCommand(
            job_id="job_conf_1",
            job_type="conformer3d",
            target_handle="root_molecule",
        ),
    )

    rebound = WorkspaceApplicator.create(project_id=workspace.project_id, workspace_id=workspace.workspace_id)
    rebound = rebound.model_copy(
        update={
            "version": workspace.version,
            "nodes": dict(workspace.nodes),
            "relations": dict(workspace.relations),
            "viewport": workspace.viewport.model_copy(deep=True),
            "rules": list(workspace.rules),
            "async_jobs": dict(workspace.async_jobs),
            "handle_bindings": dict(workspace.handle_bindings),
        },
        deep=True,
    )
    original_binding = rebound.handle_bindings["root_molecule"]
    rebound.handle_bindings["root_molecule"] = original_binding.model_copy(
        update={"node_id": "mol_rebound"}
    )

    rebound = WorkspaceApplicator.apply_async_job_result(
        rebound,
        ApplyAsyncJobResultCommand(
            job_id="job_conf_1",
            diagnostics={"conformer_status": "ready"},
            artifact_id="art_conf_1",
            result_summary="3D conformer ready",
        ),
    )

    assert rebound.async_jobs["job_conf_1"].status == "stale"
    assert rebound.async_jobs["job_conf_1"].stale_reason


def test_async_job_result_updates_target_node_when_binding_is_current() -> None:
    workspace = WorkspaceApplicator.create(project_id="proj_ibrutinib")
    workspace = WorkspaceApplicator.create_root_molecule(
        workspace,
        CreateRootMoleculeCommand(canonical_smiles="CCO"),
    )
    workspace = WorkspaceApplicator.start_async_job(
        workspace,
        StartAsyncJobCommand(
            job_id="job_conf_2",
            job_type="conformer3d",
            target_handle="root_molecule",
        ),
    )
    workspace = WorkspaceApplicator.set_viewport(
        workspace,
        SetViewportCommand(focused_handles=["root_molecule"], reference_handle="root_molecule"),
    )
    workspace = WorkspaceApplicator.apply_async_job_result(
        workspace,
        ApplyAsyncJobResultCommand(
            job_id="job_conf_2",
            diagnostics={"conformer_status": "ready", "energy": -12.7},
            artifact_id="art_conf_2",
            hover_text="3D conformer generated",
            result_summary="3D conformer ready",
        ),
    )

    root_binding = workspace.handle_bindings["root_molecule"]
    root_node = workspace.nodes[root_binding.node_id]
    assert workspace.async_jobs["job_conf_2"].status == "completed"
    assert root_node.diagnostics["conformer_status"] == "ready"
    assert root_node.artifact_ids == ["art_conf_2"]
    assert root_node.hover_text == "3D conformer generated"
    assert workspace.async_jobs["job_conf_2"].completed_at_version == workspace.version


def test_mark_job_progress_updates_summary_and_node_diagnostics() -> None:
    workspace = WorkspaceApplicator.create(project_id="proj_ibrutinib")
    workspace = WorkspaceApplicator.create_root_molecule(
        workspace,
        CreateRootMoleculeCommand(canonical_smiles="CCO"),
    )
    workspace = WorkspaceApplicator.start_async_job(
        workspace,
        StartAsyncJobCommand(job_id="job_conf_3", job_type="conformer3d", target_handle="root_molecule"),
    )

    workspace = WorkspaceApplicator.mark_job_progress(
        workspace,
        MarkAsyncJobProgressCommand(
            job_id="job_conf_3",
            result_summary="MMFF94 optimization running",
            diagnostics={"optimizer": "mmff94"},
        ),
    )

    root_node = workspace.nodes[workspace.handle_bindings["root_molecule"].node_id]
    assert workspace.async_jobs["job_conf_3"].status == "running"
    assert workspace.async_jobs["job_conf_3"].result_summary == "MMFF94 optimization running"
    assert root_node.diagnostics["optimizer"] == "mmff94"


def test_mark_job_stale_sets_reason_without_mutating_node() -> None:
    workspace = WorkspaceApplicator.create(project_id="proj_ibrutinib")
    workspace = WorkspaceApplicator.create_root_molecule(
        workspace,
        CreateRootMoleculeCommand(canonical_smiles="CCO"),
    )
    workspace = WorkspaceApplicator.start_async_job(
        workspace,
        StartAsyncJobCommand(job_id="job_conf_4", job_type="conformer3d", target_handle="root_molecule"),
    )

    workspace = WorkspaceApplicator.mark_job_stale(
        workspace,
        MarkAsyncJobStaleCommand(
            job_id="job_conf_4",
            stale_reason="workspace replaced candidate batch",
            result_summary="ignored late conformer result",
        ),
    )

    assert workspace.async_jobs["job_conf_4"].status == "stale"
    assert workspace.async_jobs["job_conf_4"].stale_reason == "workspace replaced candidate batch"
    assert workspace.async_jobs["job_conf_4"].result_summary == "ignored late conformer result"


def test_complete_workspace_job_emits_artifact_ready_event() -> None:
    workspace = WorkspaceApplicator.create(project_id="proj_ibrutinib")
    workspace = WorkspaceApplicator.create_root_molecule(
        workspace,
        CreateRootMoleculeCommand(canonical_smiles="CCO"),
    )
    workspace = WorkspaceApplicator.start_async_job(
        workspace,
        StartAsyncJobCommand(job_id="job_conf_5", job_type="conformer3d", target_handle="root_molecule"),
    )

    updated, events = complete_workspace_job(
        workspace,
        job_id="job_conf_5",
        diagnostics={"conformer_status": "ready"},
        artifact_id="art_conf_5",
        hover_text="3D conformer generated",
        result_summary="3D conformer ready",
    )

    assert updated.async_jobs["job_conf_5"].status == "completed"
    assert any(event["type"] == "artifact.ready" and event["artifact_id"] == "art_conf_5" for event in events)
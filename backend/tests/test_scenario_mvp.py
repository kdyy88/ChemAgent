from __future__ import annotations

import pytest

from app.services.workspace import (
    CandidateSpec,
    create_three_candidates,
    initialize_scaffold_hop_session,
    launch_candidate_conformer_jobs,
    register_scaffold_hop_rules,
)

IBRUTINIB_SMILES = "CC1=C(C(=CC=C1)NC(=O)C=C)N2CC[C@H](C2)OCC=CC#N"


def test_initialize_session_register_candidates_and_launch_jobs() -> None:
    workspace = initialize_scaffold_hop_session(
        project_id="proj_ibrutinib",
        parent_smiles=IBRUTINIB_SMILES,
    )
    workspace = register_scaffold_hop_rules(workspace)
    workspace = create_three_candidates(
        workspace,
        [
            CandidateSpec(smiles="C=CC(=O)N1CCC(CC1)Oc2nccc3cc4ccccc4[nH]c23", display_name="Candidate 1"),
            CandidateSpec(smiles="C=CC(=O)N1CCC(CC1)Oc2nc3ccccc3[nH]c2C", display_name="Candidate 2"),
            CandidateSpec(smiles="C=CC(=O)N1CCC(CC1)Oc2nccc3c2[nH]cc3c4ccccc4", display_name="Candidate 3"),
        ],
    )
    workspace = launch_candidate_conformer_jobs(
        workspace,
        job_ids=["job_conf_1", "job_conf_2", "job_conf_3"],
        approval_state="pending",
    )

    assert workspace.root_handle == "root_molecule"
    assert workspace.candidate_handles == ["candidate_1", "candidate_2", "candidate_3"]
    assert workspace.viewport.focused_handles == ["root_molecule", "candidate_1", "candidate_2", "candidate_3"]
    assert len(workspace.rules) == 3
    assert set(workspace.async_jobs) == {"job_conf_1", "job_conf_2", "job_conf_3"}
    assert all(job.approval_state == "pending" for job in workspace.async_jobs.values())


def test_create_three_candidates_rejects_wrong_batch_size() -> None:
    workspace = initialize_scaffold_hop_session(
        project_id="proj_ibrutinib",
        parent_smiles=IBRUTINIB_SMILES,
    )

    with pytest.raises(Exception):
        create_three_candidates(workspace, [CandidateSpec(smiles="CCO", display_name="Only one")])
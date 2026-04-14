# ChemAgent MVP Backend Blueprint

## Goal

Deliver one stable MVP backend path for the golden scenario:

- User submits a natural-language scaffold-hop request using ibrutinib as the parent.
- Backend preserves the acrylamide warhead and enforces a fused-indole scaffold constraint.
- Backend creates 1 root molecule plus 3 candidate branches.
- Backend keeps a single viewport focused on the root plus the 3 candidates.
- Backend launches 3D conformer jobs for the 3 candidates.
- Backend streams text, task progress, workspace deltas, artifact pointers, and approval or resume events in parallel.

This blueprint does not target a generic project graph platform. It targets a controlled, demonstrable, chemically useful MVP.

## Non-Goals

- No generic project-scale molecule graph.
- No full multi-tenant storage rewrite.
- No broad capability registry or runtime platform consolidation.
- No graph database.
- No large-scale concurrency or audit platform.

## Delivery Standard

The MVP is only complete when all of the following are true:

1. A single natural-language request can create a stable root plus 3-candidate workspace projection.
2. The projection exposes semantic handles instead of raw node identifiers to the LLM.
3. The 3 candidate conformer jobs are long-running, resumable, and stale-safe.
4. The SSE stream emits text events and workspace events together.
5. Approval, reject, and modify all preserve workspace consistency.
6. End-to-end tests cover the full golden path.

## Golden Path Contract

### Input

Natural-language request similar to:

"Use ibrutinib as the parent, preserve the acrylamide warhead, require a fused indole scaffold, generate 3 candidates, compare parent and children in one viewport, and generate 3D conformers for the candidates."

### Output

- Root molecule node.
- Exactly 3 candidate molecule nodes.
- Rule set entries for warhead preservation, fused-indole requirement, and candidate count.
- Single viewport focused on `root_molecule`, `candidate_1`, `candidate_2`, and `candidate_3`.
- Async job pointers for 3 conformer jobs.
- Artifact pointers for 3D outputs.
- SSE events describing all state transitions.

## Architecture Boundaries

### Truth Layer

`WorkspaceProjection` is the only workspace truth.

- Agent state may cache it.
- SSE may emit deltas from it.
- Tools may contribute structured results.
- Only the workspace application layer may mutate it.

### Semantic Handle Layer

The LLM must not depend on real `node_id`, `job_id`, or artifact storage internals.

Allowed semantic handles for the MVP:

- `root_molecule`
- `candidate_1`
- `candidate_2`
- `candidate_3`
- `active_view`

### Controlled Write Layer

All workspace writes must flow through application services and `WorkspaceApplicator`.

- No direct node mutation inside planner.
- No direct node mutation inside executor.
- No direct node mutation inside sub-agent runtime tools.
- No direct mutation from worker callbacks.

## Existing Files To Change

### `backend/app/domain/schemas/workspace.py`

Purpose after MVP:

- Canonical truth model for root, candidates, rules, viewport, and async jobs.

Required changes:

1. Add explicit MVP-facing metadata to `WorkspaceProjection`.
   - `scenario_kind: Literal["scaffold_hop_mvp"] | None`
   - `root_handle: str | None`
   - `candidate_handles: list[str]`
   - `active_view_id: str | None`
2. Extend `RuleKind` if needed for count constraints.
   - Current values are `preserve`, `require`, `note`.
   - Add `limit` or `target` if rule semantics need to distinguish numeric targets.
3. Extend `AsyncJobPointer` for stale-safe async handling.
   - `requested_at_version: int`
   - `completed_at_version: int | None`
   - `approval_state: Literal["not_required", "pending", "approved", "rejected", "modified"]`
   - `job_args: dict[str, Any]`
4. Add minimal delta models so event payloads are schema-backed instead of loose dictionaries.
   - `WorkspaceDelta`
   - `WorkspaceDeltaOp`
   - `WorkspaceEventRecord`
5. Add validation helpers or model methods for the invariant:
   - At most one root handle.
   - At most 3 active candidate handles for the MVP flow.

Acceptance checks:

- Projection can represent 1 root plus 3 candidates without freeform conventions.
- Async job pointers can detect version drift.
- Delta payloads are serializable and typed.

### `backend/app/services/workspace/applicator.py`

Purpose after MVP:

- Single mutation gateway for workspace truth.

Required changes:

1. Keep existing methods, but add explicit scenario helpers.
   - `initialize_scaffold_hop_workspace(...)`
   - `create_candidate_batch(...)`
   - `set_single_comparison_view(...)`
   - `mark_job_progress(...)`
   - `mark_job_stale(...)`
2. Introduce a delta-emitting path.
   - Every mutating method should be able to return both `WorkspaceProjection` and `WorkspaceDelta`.
   - If method signatures become too noisy, add parallel helpers such as `apply_and_diff(...)`.
3. Harden stale logic.
   - Existing async stale detection checks handle rebinding.
   - Extend it to reject async results when `base_workspace_version` is older than the latest valid scenario version.
4. Add semantic-handle guardrails.
   - Reject candidate handles outside `candidate_1..candidate_3` for this scenario service.
5. Add approval mutation helpers.
   - `approve_job(...)`
   - `reject_job(...)`
   - `modify_job(...)`

Acceptance checks:

- No graph mutation is needed outside the applicator.
- Every mutation has a stable delta representation.
- Late async results become stale instead of corrupting the current graph.

### `backend/app/domain/schemas/api.py`

Purpose after MVP:

- Stable contract for SSE event envelopes and chat control payloads.

Required changes:

1. Extend `ServerEventType` to cover the full MVP lifecycle.
   - Add `approval_required`
   - Add `job.stale`
   - Add `workspace.rule_added` only if more granular client rendering is needed
2. Rename or align viewport event naming.
   - Current type is `viewport.changed`
   - Keep or rename, but use one consistent event name everywhere
3. Add typed payload models for key event classes.
   - `WorkspaceDeltaPayload`
   - `JobEventPayload`
   - `ApprovalRequiredPayload`
   - `ArtifactReadyPayload`
4. Tighten `ApproveToolRequest`.
   - Add `target_job_id: str | None`
   - Add `modify_args` schema or documented allowed keys for conformer jobs
5. Add a read model for workspace fetch if the frontend needs polling fallback.
   - `WorkspaceSnapshotResponse`

Acceptance checks:

- SSE event payloads are schema-defined.
- Approval requests are no longer freeform.
- Chat and workspace consumers can share one envelope format.

### `backend/app/domain/schemas/agent.py`

Purpose after MVP:

- Carry workspace truth, event buffers, and golden-path control state inside graph execution.

Required changes:

1. Add explicit golden-path control fields.
   - `scenario_kind: str | None`
   - `workspace_projection: WorkspaceProjection | None` if not already stable
   - `workspace_events: list[dict[str, Any]]` or typed event list
   - `candidate_generation_status: str | None`
   - `pending_approval_job_ids: list[str]`
2. Add semantic-handle fields.
   - `active_handle: str | None`
   - `candidate_handles: list[str]`
3. Add recovery bookkeeping.
   - `approval_context`
   - `last_workspace_version`

Acceptance checks:

- The graph can resume after approval without reconstructing workspace state from text.
- Candidate and viewport context are explicit state, not inferred from chat history.

### `backend/app/agents/main_agent/graph.py`

Purpose after MVP:

- Route a golden-scenario request through a constrained execution path.

Required changes:

1. Add a scenario classification branch after `task_router`.
2. Introduce one or two dedicated nodes for the MVP path.
   - `golden_scenario_planner`
   - `golden_scenario_executor`
3. Keep the existing generic path for non-MVP traffic, but do not let the MVP request fall back silently.
4. Ensure approval resume returns to the scenario executor with preserved workspace state.

Acceptance checks:

- Golden-scenario requests do not depend on open-ended generic tool loops.
- Non-MVP requests still use the existing path.

### `backend/app/agents/nodes/router.py`

Purpose after MVP:

- Detect whether the request should enter the scaffold-hop MVP path.

Required changes:

1. Add a lightweight classifier for:
   - parent molecule present or inferable
   - scaffold-hop style request
   - structural constraints present
   - candidate-count or compare intent present
2. Set state markers for the downstream planner.
3. Prefer deterministic classification rules before LLM reasoning.

Acceptance checks:

- The golden request is routed consistently.
- The router does not rely on brittle freeform prompt parsing.

### `backend/app/agents/nodes/planner.py`

Purpose after MVP:

- Produce a finite execution plan for the golden path.

Required changes:

1. Add a structured plan output for the scenario.
   - normalize parent reference
   - register research rules
   - create candidate batch
   - set viewport
   - launch conformer jobs
2. Move away from open-ended subtasks for this path.
3. Persist a concise plan summary for approval and audit.

Acceptance checks:

- Planner output is deterministic enough to drive the executor without improvising IDs.
- The plan can be shown to the user before heavy actions if needed.

### `backend/app/agents/nodes/executor.py`

Purpose after MVP:

- Orchestrate controlled application services instead of mutating workspace indirectly through arbitrary tool effects.

Required changes:

1. Split generic tool execution from scenario execution.
2. Introduce a scenario command dispatcher.
   - execute parent normalization
   - execute rule registration
   - execute candidate generation
   - execute viewport update
   - launch conformer jobs
3. Use semantic handles only.
4. Keep current legacy auto-harvest only for the generic path.
5. Add approval handling for conformer jobs.
   - `approve` continues queued jobs
   - `reject` marks queued jobs rejected or cancelled
   - `modify` only allows whitelisted parameters like `forcefield` and `steps`
6. Ensure sub-agent outputs are post-validated before any workspace mutation.

Acceptance checks:

- The MVP path no longer depends on implicit molecule tree side effects.
- Approvals cannot mutate arbitrary tool payloads.

### `backend/app/agents/main_agent/engine.py`

Purpose after MVP:

- Emit two synchronized streams: assistant stream and workspace stream.

Required changes:

1. Consume typed workspace events from graph state.
2. Emit SSE events for:
   - `workspace.delta`
   - `molecule.upserted`
   - `relation.upserted`
   - `viewport.changed` or chosen equivalent
   - `job.started`
   - `job.progress`
   - `job.completed`
   - `job.stale`
   - `artifact.ready`
   - `approval_required`
3. Keep artifact collapse behavior.
4. Ensure event ordering is stable enough for a single-view frontend.
   - mutation event first
   - artifact pointer event second
   - assistant summary later
5. Add a helper to drain and clear workspace event buffers from state.

Acceptance checks:

- Text streaming still works.
- Workspace events appear in the same run without waiting for the final answer.

### `backend/app/api/v1/chat.py`

Purpose after MVP:

- Expose the golden-path SSE experience and minimal read-side APIs.

Required changes:

1. Keep `/stream`, `/approve`, `/artifacts/{artifact_id}`, and `/plans/{plan_id}`.
2. Add minimal workspace read endpoints if the frontend needs fallback reads.
   - `GET /api/v1/chat/workspace/{session_id}`
   - `GET /api/v1/chat/workspace/{session_id}/events`
3. Keep `/mvp/conformer` only if it remains useful for smoke testing.
4. Make approval validation strict and scenario-aware.

Acceptance checks:

- Frontend can read current projection if the SSE client reconnects.
- Approval requests are validated before the graph resumes.

### `backend/app/agents/contracts/protocol.py`

Purpose after MVP:

- Keep sub-agent delegation structured while limiting its authority.

Required changes:

1. Preserve structured completion and failure contracts.
2. Add an explicit field or convention showing whether output is advisory or mutation-ready.
3. Ensure `advisory_smiles` and produced artifacts do not become workspace truth until validated by the parent executor.
4. Document that sub-agents cannot invent semantic handles.

Acceptance checks:

- Sub-agent outputs are useful but never authoritative.
- Parent execution remains deterministic.

### `backend/app/services/task_runner/bridge.py`

Purpose after MVP:

- Create job envelopes suitable for stale-safe workspace jobs.

Required changes:

1. Include workspace context in task envelopes.
   - `session_id`
   - `workspace_id`
   - `target_handle`
   - `base_workspace_version`
   - `job_args`
2. Return enough metadata for the engine to emit `job.started` immediately.
3. Keep in-process fallback behavior for local development.

Acceptance checks:

- Worker callbacks can validate whether their results still apply.

### `backend/app/services/task_runner/worker.py`

Purpose after MVP:

- Execute 3D work and return stale-safe results.

Required changes:

1. Keep existing chemistry dispatch.
2. Include job context in worker results.
   - `job_id`
   - `target_handle`
   - `base_workspace_version`
   - `artifact_id`
   - `diagnostics`
   - `result_summary`
3. Emit enough metadata for the caller to distinguish:
   - completed
   - failed
   - stale
4. Restrict modify-path arguments to a whitelist.

Acceptance checks:

- Worker success does not imply workspace success.
- The caller can reject stale results cleanly.

### `backend/app/services/chem_engine/rdkit_ops.py`

Purpose after MVP:

- Provide the deterministic chemistry normalization and rule checks needed before any molecule enters workspace truth.

Required changes:

1. Create one standard intake helper for the MVP path.
   - validate smiles
   - canonicalize
   - strip salts if needed
   - neutralize if needed
2. Add scaffold and warhead validation helpers for the golden path.
   - detect acrylamide warhead retention
   - detect fused-indole scaffold presence
3. Return structured diagnostics suitable for workspace nodes.

Acceptance checks:

- Every root or candidate node has normalized chemistry metadata.
- Invalid but repairable inputs can be retried.

### `backend/app/services/chem_engine/babel_ops.py`

Purpose after MVP:

- Provide deterministic long-task chemistry outputs.

Required changes:

1. Keep conformer generation as the primary long-running path.
2. Ensure output metadata is sufficient for workspace hover text and artifact labels.
3. Surface actual forcefield used when fallback occurs.

Acceptance checks:

- Conformer artifacts are user-comprehensible.
- Forcefield fallback is not hidden.

## New Files To Add

### `backend/app/services/workspace/delta.py`

Purpose:

- Compute typed deltas between old and new `WorkspaceProjection` values.

Contents:

- `compute_workspace_delta(before, after) -> WorkspaceDelta`
- helpers for node upsert, relation upsert, viewport change, rules change, job change

Reason:

- Keeps diff logic out of the applicator and engine.

### `backend/app/services/workspace/scenario_mvp.py`

Purpose:

- Scenario-specific application service layer for the golden path.

Contents:

- `initialize_scaffold_hop_session(...)`
- `register_scaffold_hop_rules(...)`
- `create_three_candidates(...)`
- `launch_candidate_conformer_jobs(...)`
- `apply_conformer_completion(...)`

Reason:

- Prevents generic workspace logic from being polluted by MVP-only rules.

### `backend/app/agents/nodes/golden_scenario.py`

Purpose:

- Scenario-specific orchestration node or nodes.

Contents:

- request normalization
- structured plan generation
- controlled command execution

Reason:

- Keeps the existing generic agent path intact.

### `backend/tests/test_mvp_golden_path.py`

Purpose:

- End-to-end contract test for the single most important product flow.

Coverage:

1. natural-language scaffold-hop request enters the scenario route
2. root node created
3. 3 candidate nodes created
4. viewport focuses on 4 handles
5. 3 async conformer jobs launched
6. worker completions apply or become stale correctly
7. SSE events include workspace and assistant channels

### `backend/tests/test_workspace_delta.py`

Purpose:

- Unit tests for delta generation.

Coverage:

- root creation delta
- candidate batch delta
- viewport change delta
- job started delta
- job stale delta

### `backend/tests/test_approval_flow_mvp.py`

Purpose:

- Contract tests for approve, reject, and modify in the MVP path.

Coverage:

- approve continues conformer jobs
- reject preserves current workspace and marks queued work rejected or cancelled
- modify only accepts whitelisted job arguments

## Recommended Implementation Order

### Step 1

Stabilize truth and delta primitives.

- `backend/app/domain/schemas/workspace.py`
- `backend/app/services/workspace/applicator.py`
- `backend/app/services/workspace/delta.py`
- `backend/tests/test_workspace_applicator.py`
- `backend/tests/test_workspace_delta.py`

### Step 2

Add the scenario application service and routing path.

- `backend/app/services/workspace/scenario_mvp.py`
- `backend/app/agents/nodes/router.py`
- `backend/app/agents/nodes/planner.py`
- `backend/app/agents/nodes/golden_scenario.py`
- `backend/app/agents/main_agent/graph.py`

### Step 3

Wire SSE event flow and workspace read-side support.

- `backend/app/domain/schemas/api.py`
- `backend/app/agents/main_agent/engine.py`
- `backend/app/api/v1/chat.py`

### Step 4

Harden async chemistry execution and approval behavior.

- `backend/app/services/task_runner/bridge.py`
- `backend/app/services/task_runner/worker.py`
- `backend/app/agents/nodes/executor.py`
- `backend/tests/test_approval_flow_mvp.py`

### Step 5

Add chemistry-specific normalization and rule guards.

- `backend/app/services/chem_engine/rdkit_ops.py`
- `backend/app/services/chem_engine/babel_ops.py`
- `backend/app/agents/contracts/protocol.py`

### Step 6

Close the loop with the end-to-end test.

- `backend/tests/test_mvp_golden_path.py`
- `backend/tests/test_engine.py`
- `backend/tests/test_executor.py`

## Event Protocol For The MVP

The backend should emit these event types during the golden path:

1. `run.started`
2. `turn.status`
3. `assistant.delta`
4. `workspace.delta`
5. `molecule.upserted`
6. `relation.upserted`
7. `viewport.changed`
8. `job.started`
9. `job.progress`
10. `job.completed`
11. `job.stale`
12. `artifact.ready`
13. `approval_required`
14. `assistant.done`
15. `run.finished`

## Approval Contract For Conformer Jobs

### Approve

- Continue queued conformer jobs using the current approved arguments.

### Reject

- Do not mutate existing molecule nodes.
- Mark relevant queued jobs as rejected or cancelled.
- Keep current workspace projection valid.

### Modify

- Allow only whitelisted keys such as `forcefield` and `steps`.
- Revalidate modified values before requeueing.
- Preserve the original semantic target handle.

## Testing Gate

The MVP is not done until all these tests exist and pass:

1. Workspace applicator tests for root, candidate, viewport, and stale jobs.
2. Workspace delta tests for all major mutation types.
3. Approval flow tests for approve, reject, and modify.
4. End-to-end golden path test covering one root plus three candidates plus conformer jobs.
5. Engine tests proving assistant stream and workspace event stream coexist.

## Success Definition

The backend is considered MVP-complete when a developer can run one test or one manual session and observe:

1. ibrutinib loaded as the root node
2. 3 valid candidates added as children
3. one viewport focused on all 4 molecules
4. three conformer jobs launched and tracked
5. at least one artifact pointer returned for a candidate conformer
6. late or mismatched jobs safely marked stale
7. approval or resume behavior preserving graph integrity

"""
POST /api/v1/chat/stream  — ChemSessionEngine-powered Server-Sent Events endpoint.

Drives LangGraph's ``astream_events(version="v2")`` through a dual-layer
generator architecture defined in ``app.agents.main_agent.engine``:

- **outer layer** (``ChemSessionEngine.submit_message``): lifecycle management,
  artifact-pointer interception, error withholding & auto-retry, SSE formatting.
- **inner layer** (``ChemSessionEngine._graph_query_loop``): pure LangGraph
  execution; yields normalised Python dicts, no SSE concerns.

SSE event schema
────────────────
Each ``data:`` line carries a JSON object with a ``type`` discriminator:

  type="token"         — streaming text token from an LLM node
  type="node_start"    — a named graph node began executing
  type="node_end"      — a named graph node finished
  type="tool_start"    — an @tool call started
  type="tool_end"      — an @tool call finished with result
  type="artifact"      — a rich artifact (molecule image, descriptor table)
  type="task_update"   — planner/task execution progress update
  type="shadow_error"  — Shadow Lab detected an invalid SMILES
  type="thinking"      — agent reasoning / status text for the UI
  type="interrupt"     — LangGraph HITL pause; awaiting user input
  type="done"          — the graph run completed (final event)
  type="error"         — unhandled exception; stream terminates

All events include a session_id and turn_id for client-side state correlation.

Usage
─────
    POST /api/v1/chat/stream
    Content-Type: application/json

    {
      "session_id": "optional-uuid-for-state-continuity",
      "turn_id":    "client-generated-uuid",
      "message":    "计算阿司匹林的 Lipinski 性质，SMILES 为 CC(=O)Oc1ccccc1C(=O)O"
    }

    → text/event-stream
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agents.config import fetch_available_models
from app.agents.main_agent.engine import ChemSessionEngine
from app.agents.main_agent.runtime import get_compiled_graph, has_persisted_session
from app.domain.store.artifact_store import get_engine_artifact
from app.domain.store.plan_store import read_plan_file
from app.domain.schemas.api import (
    ApproveToolRequest,
    ModelCatalogItem,
    ModelCatalogResponse,
    MvpConformerSmokeRequest,
    PendingJobsRequest,
    StreamChatRequest,
    WorkspaceSnapshotResponse,
)
from app.services.workspace import ensure_workspace_projection

router = APIRouter()
_MODIFY_ALLOWED_KEYS = {"forcefield", "steps"}


# ── FastAPI route ──────────────────────────────────────────────────────────────


@router.post("/stream")
async def stream_chat(req: StreamChatRequest) -> StreamingResponse:
    """ChemSessionEngine-powered SSE chat endpoint (双层生成器架构).

    Accepts a JSON body and returns a ``text/event-stream`` response.
    All heavy lifting — LangGraph execution, artifact interception, error
    withholding, and self-correction retries — is handled by
    ``ChemSessionEngine``; this route is purely responsible for HTTP concerns.
    """
    engine = ChemSessionEngine(session_id=req.session_id, turn_id=req.turn_id)
    return StreamingResponse(
        engine.submit_message(
            message=req.message,
            history=req.history,
            model=req.model,
            active_smiles=req.active_smiles,
            interrupt_context=req.interrupt_context,
            skills_enabled=req.skills_enabled,
        ),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/models", response_model=ModelCatalogResponse)
async def list_models() -> ModelCatalogResponse:
    models, warning = await fetch_available_models()
    return ModelCatalogResponse(
        source="provider" if warning is None else "fallback",
        models=[ModelCatalogItem(**item) for item in models],
        warning=warning,
    )


@router.post("/approve")
async def approve_tool(req: ApproveToolRequest) -> StreamingResponse:
    """Resume a heavy-tool Hard-Breakpoint after the user approves/rejects/modifies.

    The frontend ApprovalCard POSTs here with ``action`` + optional ``args``.
    The engine resumes the frozen LangGraph checkpoint via
    ``Command(resume={action, args})`` and returns the continuation as an
    SSE stream identical in shape to ``/stream``.
    """
    if req.action not in {"approve", "reject", "modify"}:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action '{req.action}'. Must be one of: approve, reject, modify.",
        )
    if req.action == "modify":
        resolved_args = req.resolved_args() or {}
        invalid_keys = sorted(set(resolved_args) - _MODIFY_ALLOWED_KEYS)
        if invalid_keys:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported modify args: {', '.join(invalid_keys)}. Allowed keys: {', '.join(sorted(_MODIFY_ALLOWED_KEYS))}.",
            )
    engine = ChemSessionEngine(session_id=req.session_id, turn_id=req.turn_id)
    return StreamingResponse(
        engine.resume_approval(action=req.action, args=req.resolved_args(), plan_id=req.plan_id),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/pending/poll")
async def poll_pending_jobs(req: PendingJobsRequest) -> StreamingResponse:
    engine = ChemSessionEngine(session_id=req.session_id, turn_id=req.turn_id)
    return StreamingResponse(
        engine.poll_pending_jobs(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/mvp/conformer")
async def mvp_conformer_smoke(req: MvpConformerSmokeRequest) -> StreamingResponse:
    engine = ChemSessionEngine(session_id=req.session_id, turn_id=req.turn_id)
    return StreamingResponse(
        engine.run_mvp_conformer_smoke(
            smiles=req.smiles,
            name=req.name,
            forcefield=req.forcefield,
            steps=req.steps,
        ),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ── Artifact retrieval ─────────────────────────────────────────────────────────


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    """Retrieve a data-plane artifact by ID.

    Artifacts are produced by ``ChemSessionEngine._intercept_and_collapse_artifact``
    when a tool emits bulky content (SDF, PDBQT, large descriptor matrices).
    They are stored in Redis with a 1-hour TTL and are inaccessible after expiry.
    """
    data = await get_engine_artifact(artifact_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Artifact '{artifact_id}' not found or has expired.",
        )
    return {"artifact_id": artifact_id, "data": data}


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str, session_id: str):
    """Retrieve a file-backed plan document by session and stable plan id."""
    try:
        pointer, content = read_plan_file(session_id=session_id, plan_id=plan_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "plan_id": pointer.plan_id,
        "plan_file_ref": pointer.plan_file_ref,
        "status": pointer.status,
        "summary": pointer.summary,
        "revision": pointer.revision,
        "content": content,
    }


@router.get("/workspace/{session_id}", response_model=WorkspaceSnapshotResponse)
async def get_workspace_snapshot(session_id: str) -> WorkspaceSnapshotResponse:
    if not await has_persisted_session(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    graph = get_compiled_graph()
    snapshot = await graph.aget_state(
        {
            "configurable": {
                "thread_id": session_id,
                "session_id": session_id,
            }
        }
    )
    state = snapshot.values if isinstance(snapshot.values, dict) else {}
    workspace = ensure_workspace_projection(state, project_id=session_id)
    pending_jobs = list(state.get("pending_worker_tasks") or []) if isinstance(state, dict) else []
    return WorkspaceSnapshotResponse(
        session_id=session_id,
        workspace=workspace,
        version=workspace.version,
        pending_job_count=len(pending_jobs),
    )


@router.get("/workspace/{session_id}/events")
async def get_workspace_events(session_id: str):
    if not await has_persisted_session(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    graph = get_compiled_graph()
    snapshot = await graph.aget_state(
        {
            "configurable": {
                "thread_id": session_id,
                "session_id": session_id,
            }
        }
    )
    state = snapshot.values if isinstance(snapshot.values, dict) else {}
    workspace_events = list(state.get("workspace_events") or []) if isinstance(state, dict) else []
    workspace = ensure_workspace_projection(state, project_id=session_id)
    return {
        "session_id": session_id,
        "version": workspace.version,
        "events": workspace_events,
        "pending_job_count": len(list(state.get("pending_worker_tasks") or [])) if isinstance(state, dict) else 0,
    }


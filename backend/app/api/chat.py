"""
WebSocket chat handler — v2 stateless architecture.

Concurrency model:
  - One ``asyncio.Lock`` per WS connection serialises concurrent messages on
    the same connection without blocking the event loop.
  - Per turn: AgentTeam (~9 AG2 objects) built fresh, used, then immediately
    deleted (GC frees memory) — no persistent in-process agent objects.
  - Phase 2 (specialist LLM calls) run in the global IO_POOL.
  - Phase 3 (synthesis) streams directly via AsyncOpenAI in the event loop.
  - Session state (turn history, model prefs) lives in Redis with 30-min TTL.
"""

from __future__ import annotations

import asyncio
from queue import Queue
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.protocol import EventEnvelope, SessionControlMessage, UserMessage
from app.api.event_bridge import (
    stream_greeting,
    stream_specialists,
    stream_synthesis_async,
)
from app.api import sessions
from app.core.executor import IO_POOL
from app.core.network import is_origin_allowed
from app.core.tooling import tool_registry

router = APIRouter()


# ── WebSocket helpers ─────────────────────────────────────────────────────────


async def _pump_queue_to_websocket(websocket: WebSocket, queue: Queue) -> None:
    """Drain frames from a synchronous Queue into the WebSocket.

    Reads via ``run_in_executor`` so the event loop is never blocked waiting
    for the thread-side producer to put the next frame.
    """
    loop = asyncio.get_running_loop()
    while True:
        item = await loop.run_in_executor(None, queue.get)
        if item is None:
            return
        await websocket.send_json(item)


async def _stream_turn(
    *,
    websocket: WebSocket,
    session_id: str,
    agent_models: dict,
    prompt: str,
    turn_id: str,
    connection_lock: asyncio.Lock,
) -> None:
    """Execute a complete turn: routing → specialists → synthesis → save.

    Uses a connection-scoped asyncio.Lock (not a session-level threading.Lock)
    so concurrent messages on the same WebSocket connection are handled safely
    without crossing event-loop boundaries.
    """
    if connection_lock.locked():
        await websocket.send_json(
            EventEnvelope(
                type="run.failed",
                session_id=session_id,
                turn_id=turn_id,
                payload={"error": "A run is already active for this session."},
            ).to_wire()
        )
        return

    async with connection_lock:
        run_id = f"run_{uuid4().hex}"
        output_queue: Queue = Queue()
        summaries_out: list = []

        await websocket.send_json(
            EventEnvelope(
                type="run.started",
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
                payload={"prompt": prompt},
            ).to_wire()
        )
        await websocket.send_json(
            EventEnvelope(
                type="turn.status",
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
                payload={"phase": "routing", "message": "正在分析请求…"},
            ).to_wire()
        )

        # ── Phase 1: routing + Phase 2 setup (blocking, run in thread) ───────
        turn_history = await sessions.get_turn_history(session_id)

        try:
            plan, agent_team, _ = await asyncio.to_thread(
                sessions.build_run_plan, prompt, turn_history, agent_models
            )
        except Exception as exc:
            await websocket.send_json(
                EventEnvelope(
                    type="run.failed",
                    session_id=session_id,
                    turn_id=turn_id,
                    run_id=run_id,
                    payload={"error": str(exc)},
                ).to_wire()
            )
            return

        # ── Phase 2: drain specialists via IO_POOL (non-blocking for event loop)
        IO_POOL.submit(
            stream_specialists,
            plan=plan,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            output_queue=output_queue,
            summaries_out=summaries_out,
        )
        await _pump_queue_to_websocket(websocket, output_queue)

        # ── Phase 3: async synthesis directly to websocket ────────────────────
        try:
            await stream_synthesis_async(
                synthesis_factory=plan.synthesis_factory,
                summaries=summaries_out,
                websocket=websocket,
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
            )
        finally:
            # Free the 9 AG2 agent objects immediately after this turn
            del agent_team

        # ── Persist turn summary to Redis ─────────────────────────────────────
        result_summary = "; ".join(
            s.summary for s in summaries_out if s.success and s.summary
        ) or "无结果"
        await sessions.push_turn(session_id, prompt, result_summary)


async def _stream_greeting(
    *,
    websocket: WebSocket,
    session_id: str,
    agent_models: dict,
    connection_lock: asyncio.Lock,
) -> None:
    """Stream a greeting for newly-created sessions."""
    turn_id = f"greeting_{uuid4().hex}"
    run_id = f"run_{uuid4().hex}"
    output_queue: Queue = Queue()

    async with connection_lock:
        await websocket.send_json(
            EventEnvelope(
                type="run.started",
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
                payload={"prompt": "", "is_greeting": True},
            ).to_wire()
        )

        IO_POOL.submit(
            stream_greeting,
            agent_models=agent_models,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            output_queue=output_queue,
        )
        await _pump_queue_to_websocket(websocket, output_queue)


async def _init_session(
    websocket: WebSocket,
) -> tuple[str, bool, dict]:
    """Handshake: parse the initial control message and return session state.

    Returns (session_id, is_new, agent_models).
    """
    initial_message = await websocket.receive_json()
    control = SessionControlMessage.model_validate(initial_message)

    requested_id = control.session_id if control.type == "session.resume" else None
    agent_models: dict = {}
    if control.type == "session.start" and control.agent_models:
        agent_models = control.agent_models

    is_new = True
    session_id: str

    if requested_id and await sessions.session_exists(requested_id):
        meta = await sessions.get_session_meta(requested_id)
        session_id = requested_id
        agent_models = (meta or {}).get("agent_models", agent_models)
        is_new = False
    else:
        session_id = await sessions.create_session(agent_models)

    resumed = not is_new and requested_id == session_id

    await websocket.send_json(
        EventEnvelope(
            type="session.started",
            session_id=session_id,
            payload={
                "tools": tool_registry.public_catalog(),
                "resumed": resumed,
                "has_greeting": is_new,
            },
        ).to_wire()
    )
    return session_id, is_new, agent_models


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    if not is_origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    # Connection-scoped lock: serialises concurrent turns on THIS connection.
    # asyncio.Lock is lightweight and lives only as long as the WS connection.
    connection_lock = asyncio.Lock()

    try:
        session_id, is_new, agent_models = await _init_session(websocket)

        if is_new:
            await _stream_greeting(
                websocket=websocket,
                session_id=session_id,
                agent_models=agent_models,
                connection_lock=connection_lock,
            )

        while True:
            raw_message = await websocket.receive_json()
            incoming = UserMessage.model_validate(raw_message)

            if incoming.type == "session.clear":
                await sessions.clear_session(session_id)
                new_models: dict = incoming.agent_models or agent_models
                session_id = await sessions.create_session(new_models)
                agent_models = new_models
                await websocket.send_json(
                    EventEnvelope(
                        type="session.started",
                        session_id=session_id,
                        payload={
                            "tools": tool_registry.public_catalog(),
                            "resumed": False,
                            "has_greeting": True,
                        },
                    ).to_wire()
                )
                await _stream_greeting(
                    websocket=websocket,
                    session_id=session_id,
                    agent_models=agent_models,
                    connection_lock=connection_lock,
                )
                continue

            if incoming.type != "user.message":
                await websocket.send_json(
                    EventEnvelope(
                        type="run.failed",
                        session_id=session_id,
                        payload={"error": f"Unsupported message type: {incoming.type}"},
                    ).to_wire()
                )
                continue

            prompt = incoming.content.strip()
            if not prompt:
                await websocket.send_json(
                    EventEnvelope(
                        type="run.failed",
                        session_id=session_id,
                        turn_id=incoming.turn_id,
                        payload={"error": "Prompt cannot be empty."},
                    ).to_wire()
                )
                continue

            await _stream_turn(
                websocket=websocket,
                session_id=session_id,
                agent_models=agent_models,
                prompt=prompt,
                turn_id=incoming.turn_id or f"turn_{uuid4().hex}",
                connection_lock=connection_lock,
            )

    except WebSocketDisconnect:
        return

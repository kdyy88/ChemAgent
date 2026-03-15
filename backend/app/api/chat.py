from __future__ import annotations

import asyncio
import threading
from queue import Queue
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.protocol import EventEnvelope, SessionControlMessage, UserMessage
from app.api.event_bridge import stream_multi_agent_run
from app.api.sessions import ChatSession, session_manager
from app.core.network import is_origin_allowed
from app.core.tooling import tool_registry

router = APIRouter()


# ── WebSocket helpers ─────────────────────────────────────────────────────────


async def _pump_queue_to_websocket(websocket: WebSocket, queue: Queue) -> None:
    loop = asyncio.get_running_loop()
    while True:
        item = await loop.run_in_executor(None, queue.get)
        if item is None:
            return
        await websocket.send_json(item)


async def _stream_turn(
    websocket: WebSocket,
    session: ChatSession,
    prompt: str,
    turn_id: str,
) -> None:
    if not session.lock.acquire(blocking=False):
        await websocket.send_json(
            EventEnvelope(
                type="run.failed",
                session_id=session.session_id,
                turn_id=turn_id,
                payload={"error": "A run is already active for this session."},
            ).to_wire()
        )
        return

    run_id = f"run_{uuid4().hex}"
    output_queue: Queue = Queue()

    await websocket.send_json(
        EventEnvelope(
            type="run.started",
            session_id=session.session_id,
            turn_id=turn_id,
            run_id=run_id,
            payload={"prompt": prompt},
        ).to_wire()
    )

    # run_turn does Phase 1 (routing) synchronously; offload to thread to avoid
    # blocking the event loop during that LLM call.
    try:
        plan = await asyncio.to_thread(session.run_turn, prompt)
    except Exception as exc:
        session.lock.release()
        await websocket.send_json(
            EventEnvelope(
                type="run.failed",
                session_id=session.session_id,
                turn_id=turn_id,
                run_id=run_id,
                payload={"error": str(exc)},
            ).to_wire()
        )
        return

    threading.Thread(
        target=stream_multi_agent_run,
        kwargs={
            "plan": plan,
            "session": session,
            "turn_id": turn_id,
            "run_id": run_id,
            "output_queue": output_queue,
        },
        daemon=True,
    ).start()

    await _pump_queue_to_websocket(websocket, output_queue)


async def _init_session(websocket: WebSocket) -> ChatSession:
    initial_message = await websocket.receive_json()
    control = SessionControlMessage.model_validate(initial_message)
    requested_session_id = control.session_id if control.type == "session.resume" else None
    session, _created = session_manager.get_or_create(requested_session_id)

    await websocket.send_json(
        EventEnvelope(
            type="session.started",
            session_id=session.session_id,
            payload={
                "tools": tool_registry.public_catalog(),
                "resumed": control.type == "session.resume"
                and requested_session_id == session.session_id,
            },
        ).to_wire()
    )
    return session


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    if not is_origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    try:
        session = await _init_session(websocket)

        while True:
            raw_message = await websocket.receive_json()
            incoming = UserMessage.model_validate(raw_message)

            if incoming.type == "session.clear":
                session_manager.clear(session.session_id)
                session = session_manager.create()
                await websocket.send_json(
                    EventEnvelope(
                        type="session.started",
                        session_id=session.session_id,
                        payload={
                            "tools": tool_registry.public_catalog(),
                            "resumed": False,
                        },
                    ).to_wire()
                )
                continue

            if incoming.type != "user.message":
                await websocket.send_json(
                    EventEnvelope(
                        type="run.failed",
                        session_id=session.session_id,
                        payload={"error": f"Unsupported message type: {incoming.type}"},
                    ).to_wire()
                )
                continue

            prompt = incoming.content.strip()
            if not prompt:
                await websocket.send_json(
                    EventEnvelope(
                        type="run.failed",
                        session_id=session.session_id,
                        turn_id=incoming.turn_id,
                        payload={"error": "Prompt cannot be empty."},
                    ).to_wire()
                )
                continue

            await _stream_turn(
                websocket=websocket,
                session=session,
                prompt=prompt,
                turn_id=incoming.turn_id or f"turn_{uuid4().hex}",
            )

    except WebSocketDisconnect:
        return

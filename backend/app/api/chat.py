from __future__ import annotations

import asyncio
import threading
from queue import Queue
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.protocol import EventEnvelope, SessionControlMessage, UserMessage
from app.api.event_bridge import stream_greeting, stream_multi_agent_run
from app.api.sessions import ChatSession, session_manager
from app.core.network import is_origin_allowed
from app.core.tooling import tool_registry

router = APIRouter()


# ── WebSocket helpers ─────────────────────────────────────────────────────────


async def _send_json(websocket: WebSocket, send_lock: asyncio.Lock, payload: dict) -> None:
    async with send_lock:
        await websocket.send_json(payload)


async def _pump_queue_to_websocket(websocket: WebSocket, queue: Queue, send_lock: asyncio.Lock) -> None:
    loop = asyncio.get_running_loop()
    while True:
        item = await loop.run_in_executor(None, queue.get)
        if item is None:
            return
        try:
            await _send_json(websocket, send_lock, item)
        except (RuntimeError, WebSocketDisconnect):
            # WebSocket was closed before we finished sending — drain the queue
            # to the None sentinel so the producer thread can unblock and
            # release the session lock, then exit cleanly.
            while item is not None:
                item = await loop.run_in_executor(None, queue.get)
            return


async def _heartbeat(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
) -> None:
    """Send periodic ping frames to keep the connection alive.

    We intentionally do NOT close the connection on a missed pong.  During an
    active agent run the main loop is blocked inside _pump_queue_to_websocket
    and cannot call receive_json(), so pong replies from the client accumulate
    in the receive buffer but are never consumed.  Acting on a missing pong
    during a run would be a false positive that kills a healthy connection.
    True disconnects surface naturally as RuntimeError / WebSocketDisconnect
    on the next send or receive operation.
    """
    while True:
        await asyncio.sleep(25)
        try:
            await _send_json(websocket, send_lock, EventEnvelope(type="ping").to_wire())
        except (RuntimeError, WebSocketDisconnect):
            return


async def _stream_turn(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session: ChatSession,
    prompt: str,
    turn_id: str,
) -> None:
    if not session.lock.acquire(blocking=False):
        await _send_json(
            websocket,
            send_lock,
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

    await _send_json(
        websocket,
        send_lock,
        EventEnvelope(
            type="run.started",
            session_id=session.session_id,
            turn_id=turn_id,
            run_id=run_id,
            payload={"prompt": prompt},
        ).to_wire()
    )

    # Notify the frontend that routing is in progress so it can show a
    # meaningful status label instead of a blank spinner.
    await _send_json(
        websocket,
        send_lock,
        EventEnvelope(
            type="turn.status",
            session_id=session.session_id,
            turn_id=turn_id,
            run_id=run_id,
            payload={"phase": "routing", "message": "正在分析请求…"},
        ).to_wire()
    )

    # run_turn does Phase 1 (routing) synchronously; offload to thread to avoid
    # blocking the event loop during that LLM call.
    try:
        plan = await asyncio.to_thread(session.run_turn, prompt)
    except Exception as exc:
        session.lock.release()
        await _send_json(
            websocket,
            send_lock,
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

    await _pump_queue_to_websocket(websocket, output_queue, send_lock)



async def _stream_greeting(websocket: WebSocket, send_lock: asyncio.Lock, session: ChatSession) -> None:
    """Run the Manager greeting and stream frames to the client.

    Mirrors _stream_turn but uses a unique turn_id per invocation so that
    multiple greeting turns (e.g. after New Chat) never share a React key.
    """
    turn_id = f"greeting_{uuid4().hex}"
    run_id = f"run_{uuid4().hex}"
    output_queue: Queue = Queue()

    if not session.lock.acquire(blocking=False):
        # Should never happen on a freshly created session — skip silently.
        return

    await _send_json(
        websocket,
        send_lock,
        EventEnvelope(
            type="run.started",
            session_id=session.session_id,
            turn_id=turn_id,
            run_id=run_id,
            payload={"prompt": "", "is_greeting": True},
        ).to_wire()
    )

    threading.Thread(
        target=stream_greeting,
        kwargs={
            "session": session,
            "session_id": session.session_id,
            "turn_id": turn_id,
            "run_id": run_id,
            "output_queue": output_queue,
        },
        daemon=True,
    ).start()

    await _pump_queue_to_websocket(websocket, output_queue, send_lock)


async def _init_session(websocket: WebSocket, send_lock: asyncio.Lock) -> tuple[ChatSession, bool]:
    initial_message = await websocket.receive_json()
    control = SessionControlMessage.model_validate(initial_message)
    requested_session_id = control.session_id if control.type == "session.resume" else None
    session, created = session_manager.get_or_create(
        requested_session_id,
        agent_models=control.agent_models if control.type == "session.start" else None,
    )

    await _send_json(
        websocket,
        send_lock,
        EventEnvelope(
            type="session.started",
            session_id=session.session_id,
            payload={
                "tools": tool_registry.public_catalog(),
                "resumed": control.type == "session.resume"
                and requested_session_id == session.session_id,
                # Tell the client to block user input until the greeting finishes.
                "has_greeting": created,
            },
        ).to_wire()
    )
    return session, created


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    if not is_origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    send_lock = asyncio.Lock()
    heartbeat_task: asyncio.Task | None = None

    try:
        session, created = await _init_session(websocket, send_lock)
        heartbeat_task = asyncio.create_task(_heartbeat(websocket, send_lock))

        # For new sessions, stream a greeting — this also pre-warms the LLM
        # connection so the user's first real query gets a faster response.
        if created:
            await _stream_greeting(websocket, send_lock, session)

        while True:
            raw_message = await websocket.receive_json()
            if raw_message.get("type") == "pong":
                # Pong received — no action needed, just discard
                continue

            incoming = UserMessage.model_validate(raw_message)

            if incoming.type == "session.clear":
                session_manager.clear(session.session_id)
                session = session_manager.create(agent_models=incoming.agent_models)
                await _send_json(
                    websocket,
                    send_lock,
                    EventEnvelope(
                        type="session.started",
                        session_id=session.session_id,
                        payload={
                            "tools": tool_registry.public_catalog(),
                            "resumed": False,
                            "has_greeting": True,
                            "agent_models": session.agent_models,
                        },
                    ).to_wire()
                )
                await _stream_greeting(websocket, send_lock, session)
                continue

            if incoming.type != "user.message":
                await _send_json(
                    websocket,
                    send_lock,
                    EventEnvelope(
                        type="run.failed",
                        session_id=session.session_id,
                        payload={"error": f"Unsupported message type: {incoming.type}"},
                    ).to_wire()
                )
                continue

            prompt = incoming.content.strip()
            if not prompt:
                await _send_json(
                    websocket,
                    send_lock,
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
                send_lock=send_lock,
                session=session,
                prompt=prompt,
                turn_id=incoming.turn_id or f"turn_{uuid4().hex}",
            )

    except WebSocketDisconnect:
        return
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()

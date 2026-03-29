"""
WebSocket chat handler — async-first, no threads.

Architecture
------------
Uses AG2's ``a_run()`` → ``AsyncRunResponseProtocol`` with ``async for``
event iteration on the same event loop.  No daemon threads, no
``queue.Queue``, no ``run_in_executor``.

HITL flow
---------
1. User sends ``user.message`` → planning phase runs, streams events.
2. If brain emits ``[AWAITING_APPROVAL]``:
   - If ``session.auto_approve``: immediately runs execution.
   - Otherwise: sends ``plan.status(awaiting_approval)`` and returns to
     the receive loop.
3. User sends ``plan.approve`` → execution phase runs.
4. User sends ``plan.reject``  → session resets to idle.
5. User sends ``settings.update`` → toggles ``auto_approve``.
"""

from __future__ import annotations

import asyncio
from functools import partial
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.events import stream_execution, stream_planning
from app.api.protocol import EventEnvelope, SessionControlMessage, UserMessage
from app.api.sessions import ChatSession, session_manager
from app.core.network import is_origin_allowed
from app.tools import public_catalog

router = APIRouter()


# ── WebSocket helpers ─────────────────────────────────────────────────────────


async def _send_json(websocket: WebSocket, send_lock: asyncio.Lock, payload: dict) -> None:
    async with send_lock:
        await websocket.send_json(payload)


async def _heartbeat(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
) -> None:
    """Send periodic ping frames to keep the connection alive."""
    while True:
        await asyncio.sleep(25)
        try:
            await _send_json(websocket, send_lock, EventEnvelope(type="ping").to_wire())
        except (RuntimeError, WebSocketDisconnect):
            return


# ── Per-turn state (tracks active turn_id + run_id for approval) ──────────────


class _TurnContext:
    """Tracks the active turn so ``plan.approve`` can reference it."""

    __slots__ = ("turn_id", "run_id")

    def __init__(self) -> None:
        self.turn_id: str = ""
        self.run_id: str = ""

    def set(self, turn_id: str, run_id: str) -> None:
        self.turn_id = turn_id
        self.run_id = run_id


# ── Turn orchestration ────────────────────────────────────────────────────────


async def _run_turn(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session: ChatSession,
    prompt: str,
    turn_id: str,
    turn_ctx: _TurnContext,
) -> None:
    """Run a full user turn: plan → (optional auto-approve) → execute.

    Acquires ``session.lock`` (asyncio.Lock) for the duration. If the brain
    enters ``awaiting_approval`` and ``auto_approve`` is off, the function
    **returns** after planning so the main receive loop can wait for
    ``plan.approve``.
    """
    async with session.lock:
        run_id = f"run_{uuid4().hex}"
        turn_ctx.set(turn_id, run_id)

        send_fn = partial(_send_json, websocket, send_lock)

        # run.started ──────────────────────────────────────────────────────
        await send_fn(
            EventEnvelope(
                type="run.started",
                session_id=session.session_id,
                turn_id=turn_id,
                run_id=run_id,
                payload={"prompt": prompt},
            ).to_wire()
        )

        # turn.status → planning ──────────────────────────────────────────
        await send_fn(
            EventEnvelope(
                type="turn.status",
                session_id=session.session_id,
                turn_id=turn_id,
                run_id=run_id,
                payload={"phase": "planning", "message": "正在分析请求…"},
            ).to_wire()
        )

        # Phase 1: Planning ───────────────────────────────────────────────
        await stream_planning(
            session=session,
            prompt=prompt,
            turn_id=turn_id,
            run_id=run_id,
            send_fn=send_fn,
        )

        # After planning: decide whether to auto-approve or wait ──────────
        if session.state == "awaiting_approval":
            if session.auto_approve:
                await send_fn(
                    EventEnvelope(
                        type="turn.status",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        run_id=run_id,
                        payload={"phase": "executing", "message": "自动批准，开始执行…"},
                    ).to_wire()
                )
                await stream_execution(
                    session=session,
                    approval_text="Approved. Please proceed with all planned steps.",
                    turn_id=turn_id,
                    run_id=run_id,
                    send_fn=send_fn,
                )
            # else: return to receive loop — frontend shows approve/reject


async def _run_approval(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session: ChatSession,
    turn_ctx: _TurnContext,
    approval_text: str,
) -> None:
    """Resume execution after user approves the plan."""
    async with session.lock:
        send_fn = partial(_send_json, websocket, send_lock)
        turn_id = turn_ctx.turn_id
        run_id = turn_ctx.run_id

        await send_fn(
            EventEnvelope(
                type="turn.status",
                session_id=session.session_id,
                turn_id=turn_id,
                run_id=run_id,
                payload={"phase": "executing", "message": "计划已批准，开始执行…"},
            ).to_wire()
        )

        await stream_execution(
            session=session,
            approval_text=approval_text or "Approved. Please proceed with all planned steps.",
            turn_id=turn_id,
            run_id=run_id,
            send_fn=send_fn,
        )


_STATIC_GREETING = (
    "你好！我是 ChemAgent，专业化学分析助手 🧪\n"
    "我能帮你查询化合物 SMILES 结构、分析 Lipinski 五规则、提取 Murcko 骨架、"
    "绘制分子结构图、计算相似度、搜索最新文献等。\n"
    "请告诉我你想研究哪个化合物或化学问题？"
)


async def _send_static_greeting(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session: ChatSession,
) -> None:
    """Send a pre-defined static greeting — zero LLM calls."""
    turn_id = f"greeting_{uuid4().hex}"
    run_id = f"run_{uuid4().hex}"
    send_fn = partial(_send_json, websocket, send_lock)

    await send_fn(
        EventEnvelope(
            type="run.started",
            session_id=session.session_id,
            turn_id=turn_id,
            run_id=run_id,
            payload={"prompt": "", "is_greeting": True},
        ).to_wire()
    )
    await send_fn(
        EventEnvelope(
            type="assistant.message",
            session_id=session.session_id,
            turn_id=turn_id,
            run_id=run_id,
            payload={"sender": "planner", "message": _STATIC_GREETING},
        ).to_wire()
    )
    await send_fn(
        EventEnvelope(
            type="run.finished",
            session_id=session.session_id,
            turn_id=turn_id,
            run_id=run_id,
            payload={"summary": "", "last_speaker": "planner"},
        ).to_wire()
    )


# ── Session initialisation ───────────────────────────────────────────────────


async def _init_session(
    websocket: WebSocket, send_lock: asyncio.Lock
) -> tuple[ChatSession, bool]:
    initial_message = await websocket.receive_json()
    control = SessionControlMessage.model_validate(initial_message)
    requested_session_id = control.session_id if control.type == "session.resume" else None
    session, created = await session_manager.get_or_create(
        requested_session_id,
        agent_models=control.agent_models if control.type == "session.start" else None,
    )

    is_resumed = (
        control.type == "session.resume"
        and requested_session_id == session.session_id
    )

    await _send_json(
        websocket,
        send_lock,
        EventEnvelope(
            type="session.started",
            session_id=session.session_id,
            payload={
                "tools": public_catalog(),
                "resumed": is_resumed,
                "has_greeting": created,
            },
        ).to_wire(),
    )

    # On reconnect — replay last turn state so the frontend can restore UI
    if is_resumed and not created:
        has_snapshot = (
            session.last_plan is not None
            or session.last_todo is not None
            or session.last_answer is not None
        )
        if has_snapshot:
            await _send_json(
                websocket,
                send_lock,
                EventEnvelope(
                    type="state.snapshot",
                    session_id=session.session_id,
                    turn_id=session.last_turn_id or "",
                    run_id=session.last_run_id or "",
                    payload={
                        "last_plan": session.last_plan,
                        "last_todo": session.last_todo,
                        "last_answer": session.last_answer,
                        "state": session.state,
                    },
                ).to_wire(),
            )

    return session, created


# ── Main WebSocket endpoint ──────────────────────────────────────────────────


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    if not is_origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    send_lock = asyncio.Lock()
    heartbeat_task: asyncio.Task | None = None
    turn_ctx = _TurnContext()

    try:
        session, created = await _init_session(websocket, send_lock)
        heartbeat_task = asyncio.create_task(_heartbeat(websocket, send_lock))

        if created:
            await _send_static_greeting(websocket, send_lock, session)

        while True:
            raw_message = await websocket.receive_json()
            msg_type = raw_message.get("type", "")

            # ── Pong (keepalive reply) ────────────────────────────────────
            if msg_type == "pong":
                continue

            # ── Plan approval ─────────────────────────────────────────────
            if msg_type == "plan.approve":
                if session.state != "awaiting_approval":
                    await _send_json(
                        websocket,
                        send_lock,
                        EventEnvelope(
                            type="run.failed",
                            session_id=session.session_id,
                            payload={"error": "No plan is awaiting approval."},
                        ).to_wire(),
                    )
                    continue
                approval_text = raw_message.get("content", "")
                await _run_approval(websocket, send_lock, session, turn_ctx, approval_text)
                continue

            # ── Plan rejection ────────────────────────────────────────────
            if msg_type == "plan.reject":
                if session.state == "awaiting_approval":
                    session.state = "idle"
                    await _send_json(
                        websocket,
                        send_lock,
                        EventEnvelope(
                            type="plan.status",
                            session_id=session.session_id,
                            turn_id=turn_ctx.turn_id,
                            run_id=turn_ctx.run_id,
                            payload={"status": "rejected"},
                        ).to_wire(),
                    )
                continue

            # ── Settings update (auto_approve toggle) ─────────────────────
            if msg_type == "settings.update":
                settings = raw_message.get("settings", {})
                if "auto_approve" in settings:
                    session.auto_approve = bool(settings["auto_approve"])
                await _send_json(
                    websocket,
                    send_lock,
                    EventEnvelope(
                        type="settings.updated",
                        session_id=session.session_id,
                        payload={"auto_approve": session.auto_approve},
                    ).to_wire(),
                )
                continue

            # ── Standard messages (user.message, session.clear) ───────────
            incoming = UserMessage.model_validate(raw_message)

            if incoming.type == "session.clear":
                await session_manager.clear(session.session_id)
                session = await session_manager.create(agent_models=incoming.agent_models)
                await _send_json(
                    websocket,
                    send_lock,
                    EventEnvelope(
                        type="session.started",
                        session_id=session.session_id,
                        payload={
                            "tools": public_catalog(),
                            "resumed": False,
                            "has_greeting": True,
                            "agent_models": session.agent_models,
                        },
                    ).to_wire(),
                )
                await _send_static_greeting(websocket, send_lock, session)
                continue

            if incoming.type != "user.message":
                await _send_json(
                    websocket,
                    send_lock,
                    EventEnvelope(
                        type="run.failed",
                        session_id=session.session_id,
                        payload={"error": f"Unsupported message type: {incoming.type}"},
                    ).to_wire(),
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
                    ).to_wire(),
                )
                continue

            await _run_turn(
                websocket=websocket,
                send_lock=send_lock,
                session=session,
                prompt=prompt,
                turn_id=incoming.turn_id or f"turn_{uuid4().hex}",
                turn_ctx=turn_ctx,
            )

    except WebSocketDisconnect:
        return
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()

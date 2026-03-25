"""
Event bridge — converts AG2 ``AsyncRunResponseProtocol`` events into
WebSocket frames for the frontend.

Async-first: uses ``async for event in response.events`` (non-blocking)
and calls ``await send_fn(frame)`` directly — no intermediate Queue,
no daemon threads, no ``run_in_executor``.

HITL integration
----------------
- ``TextEvent`` content is scanned for ``<plan>``, ``<todo>`` XML tags and
  sentinel keywords (``[AWAITING_APPROVAL]``, ``[TERMINATE]``).
- Parsed plan / todo data is emitted as dedicated event types
  (``plan.proposed``, ``todo.progress``, ``plan.status``) alongside the
  backward-compatible ``assistant.message``.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Awaitable, Callable
from uuid import uuid4

from autogen.events.agent_events import (
    ErrorEvent,
    ExecuteFunctionEvent,
    ExecutedFunctionEvent,
    RunCompletionEvent,
    TextEvent,
    ToolCallEvent,
)

from app.agents.reasoning_client import ReasoningChunkEvent
from app.api.protocol import EventEnvelope
from app.core.tooling import parse_tool_payload, tool_result_store

if TYPE_CHECKING:
    from app.api.sessions import ChatSession

# Type alias for WebSocket send callback
SendFn = Callable[[dict], Awaitable[None]]


# ── Regex patterns ────────────────────────────────────────────────────────────

_PLAN_RE = re.compile(r"<plan>(.*?)</plan>", re.DOTALL)
_TODO_RE = re.compile(r"<todo>(.*?)</todo>", re.DOTALL)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)", re.IGNORECASE)
_DATA_URL_RE = re.compile(r"data:[^\s)]+", re.IGNORECASE)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _sanitize(content: str) -> str:
    """Remove inline image markdown and data URLs from assistant text."""
    sanitized = _MARKDOWN_IMAGE_RE.sub("", content)
    sanitized = _DATA_URL_RE.sub("[artifact]", sanitized)
    return sanitized


def _json_loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _make_frame(
    event_type: str,
    payload: dict,
    session_id: str,
    turn_id: str,
    run_id: str,
) -> dict:
    return EventEnvelope(
        type=event_type,
        session_id=session_id,
        turn_id=turn_id,
        run_id=run_id,
        payload=payload,
    ).to_wire()


# ── Core event → frames conversion ───────────────────────────────────────────


def _event_to_frames(
    *,
    event: object,
    session_id: str,
    turn_id: str,
    run_id: str,
    pending_calls: dict[str, dict],
    session: ChatSession,
    phase_state: dict[str, object],
) -> list[dict]:
    """Convert a single AG2 event into zero or more WebSocket frames."""
    frames: list[dict] = []
    payload = event.content  # type: ignore[attr-defined]

    # ── ToolCallEvent ─────────────────────────────────────────────────────
    if isinstance(event, ToolCallEvent):
        for tool_call in payload.tool_calls:
            call_id = tool_call.id or f"call_{uuid4().hex}"
            arguments = _json_loads(tool_call.function.arguments)
            tool_name = tool_call.function.name or "unknown_tool"
            pending_calls[call_id] = {"tool": tool_name, "arguments": arguments}
            frames.append(
                _make_frame(
                    "tool.call",
                    {
                        "sender": "chem_brain",
                        "tool_call_id": call_id,
                        "tool": {"name": tool_name},
                        "arguments": arguments,
                    },
                    session_id,
                    turn_id,
                    run_id,
                )
            )

    # ── ExecuteFunctionEvent (pre-execution) ──────────────────────────────
    elif isinstance(event, ExecuteFunctionEvent):
        call_id = payload.call_id or f"call_{uuid4().hex}"
        pending_calls[call_id] = {
            "tool": payload.func_name,
            "arguments": payload.arguments or {},
        }

    # ── ExecutedFunctionEvent (post-execution) ────────────────────────────
    elif isinstance(event, ExecutedFunctionEvent):
        call_id = payload.call_id or ""
        pending = pending_calls.get(call_id, {})
        tool_name = str(pending.get("tool", payload.func_name))

        # Try to read the rich ToolExecutionResult from the store.
        # The tool returns a slim JSON (success + result_id + summary) for
        # the LLM context window.  parse_tool_payload may fail on this format
        # because it uses "success" (bool) not "status" (str).  So we also
        # attempt a direct store lookup via result_id.
        result = parse_tool_payload(str(payload.content))
        if result is not None:
            result = tool_result_store.get(result.result_id) or result
        else:
            # Slim response fallback — extract result_id and look up store
            slim = _json_loads(str(payload.content))
            rid = slim.get("result_id")
            if rid:
                result = tool_result_store.get(str(rid))

        if result is None:
            # Fallback: no structured result — pass raw content
            frames.append(
                _make_frame(
                    "tool.result",
                    {
                        "sender": "executor",
                        "tool_call_id": call_id or None,
                        "tool": {"name": tool_name},
                        "status": "success" if payload.is_exec_success else "error",
                        "summary": str(payload.content),
                        "data": payload.arguments or {},
                        "artifacts": [],
                    },
                    session_id,
                    turn_id,
                    run_id,
                )
            )
        else:
            if any(
                a.kind == "image" and a.mime_type.startswith("image/")
                for a in result.artifacts
            ):
                phase_state["generated_image"] = True
            frames.append(
                _make_frame(
                    "tool.result",
                    {
                        "sender": "executor",
                        "tool_call_id": call_id or None,
                        "tool": {"name": tool_name},
                        "status": result.status,
                        "summary": result.summary,
                        "data": result.data,
                        "retry_hint": result.retry_hint,
                        "error_code": result.error_code,
                        "artifacts": [a.model_dump() for a in result.artifacts],
                    },
                    session_id,
                    turn_id,
                    run_id,
                )
            )

        # Auto-tick next unchecked todo item on successful tool execution.
        # LLMs often call tools without updating the <todo> block, leaving
        # the checklist frozen.  This gives the frontend real-time progress.
        is_success = payload.is_exec_success if hasattr(payload, "is_exec_success") else (
            result is not None and result.status == "success"
        )
        todo_lines = phase_state.get("todo_lines")
        if is_success and todo_lines:
            for i, line in enumerate(todo_lines):
                if re.match(r"^\s*-\s*\[\s*\]", line):
                    todo_lines[i] = re.sub(
                        r"\[\s*\]", "[x]", line, count=1,
                    ).rstrip()
                    if "✓" not in todo_lines[i]:
                        todo_lines[i] += " ✓"
                    break
            updated_todo = "\n".join(todo_lines)
            session.last_todo = updated_todo
            frames.append(
                _make_frame(
                    "todo.progress",
                    {"todo": updated_todo},
                    session_id,
                    turn_id,
                    run_id,
                )
            )

    # ── ReasoningChunkEvent (custom — reasoning_content from streaming) ────
    elif isinstance(event, ReasoningChunkEvent):
        frames.append(
            _make_frame(
                "thinking.delta",
                {"content": event.content},
                session_id,
                turn_id,
                run_id,
            )
        )

    # ── TextEvent (may contain <plan>, <todo>, sentinels) ─────────────────
    elif isinstance(event, TextEvent):
        content = str(payload.content or "")
        sender = str(getattr(payload, "sender", "chem_brain"))

        if not content or sender != "chem_brain":
            return frames

        # 1. Detect <plan> tags → emit plan.proposed
        plan_match = _PLAN_RE.search(content)
        if plan_match:
            plan_text = plan_match.group(1).strip()
            session.last_plan = plan_text
            frames.append(
                _make_frame(
                    "plan.proposed",
                    {"plan": plan_text},
                    session_id,
                    turn_id,
                    run_id,
                )
            )

        # 2. Detect <todo> tags → emit todo.progress
        todo_match = _TODO_RE.search(content)
        if todo_match:
            todo_text = todo_match.group(1).strip()
            # Store parsed lines so ExecutedFunctionEvent can auto-tick
            phase_state["todo_lines"] = [
                l for l in todo_text.split("\n") if l.strip()
            ]
            session.last_todo = todo_text
            frames.append(
                _make_frame(
                    "todo.progress",
                    {"todo": todo_text},
                    session_id,
                    turn_id,
                    run_id,
                )
            )

        # 3. Detect sentinels
        if "[AWAITING_APPROVAL]" in content:
            session.state = "awaiting_approval"
            frames.append(
                _make_frame(
                    "plan.status",
                    {"status": "awaiting_approval"},
                    session_id,
                    turn_id,
                    run_id,
                )
            )

        if "[TERMINATE]" in content:
            session.state = "idle"

        # 4. Emit assistant.message only for genuine user-facing answer text.
        #
        # Suppression rules:
        # • <plan> content  → always suppress (dedicated plan.proposed frame)
        # • [AWAITING_APPROVAL] → always suppress (dedicated plan.status frame)
        # • <todo> during execution phase → suppress; the "正在执行第N步…" narration
        #   that wraps the todo block is pipeline chatter, not user-facing content.
        # • <todo> on final answer (state already flipped to "idle" by [TERMINATE])
        #   → allow through after stripping the <todo> block so the report is visible.
        suppress_message = (
            plan_match is not None
            or "[AWAITING_APPROVAL]" in content
            or (todo_match is not None and session.state == "executing")
        )

        if not suppress_message:
            clean = content
            clean = clean.replace("[TERMINATE]", "")
            # Strip any <todo>…</todo> block (may appear in final summary)
            clean = _TODO_RE.sub("", clean)
            clean = _sanitize(clean).strip()

            if clean:
                # Persist last answer fragment for session snapshot on reconnect
                if session.last_answer is None:
                    session.last_answer = clean
                else:
                    session.last_answer += clean
                frames.append(
                    _make_frame(
                        "assistant.message",
                        {"sender": "Manager", "message": clean},
                        session_id,
                        turn_id,
                        run_id,
                    )
                )

    # ── RunCompletionEvent ────────────────────────────────────────────────
    elif isinstance(event, RunCompletionEvent):
        # Persist turn/run IDs for state snapshot on reconnect
        session.last_turn_id = turn_id
        session.last_run_id = run_id

        # Suppress run.finished during Phase 1 (planning) when the brain
        # has proposed a plan and is waiting for user approval.  Emitting
        # run.finished here would set the frontend turn status to "done",
        # hiding the approve/reject buttons.  The real run.finished will
        # be emitted after Phase 2 (execution) completes — or after the
        # user rejects the plan.
        if session.state != "awaiting_approval":
            frames.append(
                _make_frame(
                    "run.finished",
                    {
                        "summary": payload.summary,
                        "last_speaker": payload.last_speaker,
                    },
                    session_id,
                    turn_id,
                    run_id,
                )
            )

    # ── ErrorEvent ────────────────────────────────────────────────────────
    elif isinstance(event, ErrorEvent):
        frames.append(
            _make_frame(
                "run.failed",
                {"error": str(payload.error)},
                session_id,
                turn_id,
                run_id,
            )
        )

    return frames


# ── Public API: stream AsyncRunResponseProtocol directly ──────────────────────


async def drain_response(
    *,
    response: object,
    session: ChatSession,
    session_id: str,
    turn_id: str,
    run_id: str,
    send_fn: SendFn,
) -> None:
    """Iterate ``response.events`` (async, non-blocking) and push WS frames.

    Runs on the main event loop — no threads, no Queue.  ``send_fn`` is
    typically ``_send_json(websocket, send_lock, frame)`` curried into a
    single-argument callable.

    Must be called while holding ``session.lock`` (asyncio.Lock).
    """
    pending_calls: dict[str, dict] = {}
    phase_state: dict[str, object] = {"generated_image": False}

    try:
        async for event in response.events:  # type: ignore[attr-defined]
            for frame in _event_to_frames(
                event=event,
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
                pending_calls=pending_calls,
                session=session,
                phase_state=phase_state,
            ):
                await send_fn(frame)
    except Exception as exc:
        await send_fn(
            _make_frame(
                "run.failed",
                {"error": f"[EventBridge] {exc}"},
                session_id,
                turn_id,
                run_id,
            )
        )


async def stream_planning(
    *,
    session: ChatSession,
    prompt: str,
    turn_id: str,
    run_id: str,
    send_fn: SendFn,
) -> None:
    """Run Phase 1 (planning) and stream event frames to the client.

    After all events are consumed the session is in either
    ``awaiting_approval`` (plan generated) or ``idle`` (direct answer with
    ``[TERMINATE]``).  The caller inspects ``session.state`` to decide
    whether to wait for ``plan.approve`` or finish the turn.
    """
    session_id = session.session_id

    try:
        plan_response = await session.run_planning(prompt)
        await drain_response(
            response=plan_response,
            session=session,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            send_fn=send_fn,
        )
    except Exception as exc:
        await send_fn(
            _make_frame(
                "run.failed",
                {"error": str(exc)},
                session_id,
                turn_id,
                run_id,
            )
        )
        session.state = "idle"


async def stream_execution(
    *,
    session: ChatSession,
    approval_text: str,
    turn_id: str,
    run_id: str,
    send_fn: SendFn,
) -> None:
    """Run Phase 2 (execution) after plan approval and stream frames.

    Resets ``session.state`` to ``idle`` when done.
    """
    session_id = session.session_id

    try:
        exec_response = await session.run_execution(approval_text)
        await drain_response(
            response=exec_response,
            session=session,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            send_fn=send_fn,
        )
    except Exception as exc:
        await send_fn(
            _make_frame(
                "run.failed",
                {"error": str(exc)},
                session_id,
                turn_id,
                run_id,
            )
        )
    finally:
        session.state = "idle"


async def stream_greeting(
    *,
    session: ChatSession,
    turn_id: str,
    run_id: str,
    send_fn: SendFn,
) -> None:
    """Generate a ChemBrain greeting and stream it to the client."""
    session_id = session.session_id

    try:
        response = await session.generate_greeting()
        await drain_response(
            response=response,
            session=session,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            send_fn=send_fn,
        )
    except Exception as exc:
        await send_fn(
            _make_frame(
                "run.failed",
                {"error": str(exc)},
                session_id,
                turn_id,
                run_id,
            )
        )

"""
Event bridge — converts AG2 ``AsyncRunResponseProtocol`` events into
WebSocket frames for the frontend.

Async-first: uses ``async for event in response.events`` (non-blocking)
and calls ``await send_fn(frame)`` directly — no intermediate Queue,
no daemon threads, no ``run_in_executor``.

HITL integration (tool-driven, no sentinel strings)
----------------------------------------------------
- ``ExecutedFunctionEvent`` is scanned for control tool names:
  - ``submit_plan_for_approval`` → session.state="awaiting_approval",
    emits ``plan.status`` frame.
  - ``finish_workflow``           → session.state="idle".
- ``TextEvent`` content is scanned for ``<plan>`` and ``<todo>`` XML tags
  and parsed into dedicated event types (``plan.proposed``, ``todo.progress``).
- No sentinel keyword scanning (``[AWAITING_APPROVAL]``, ``[TERMINATE]``,
  ``[ROUTE: xxx]``) — these have been replaced by tool calls.
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
    GroupChatRunChatEvent,
    RunCompletionEvent,
    TextEvent,
    ToolCallEvent,
)
from autogen.events.client_events import StreamEvent

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
        tool_sender = str(getattr(payload, "sender", "agent"))
        for tool_call in payload.tool_calls:
            call_id = tool_call.id or f"call_{uuid4().hex}"
            arguments = _json_loads(tool_call.function.arguments)
            tool_name = tool_call.function.name or "unknown_tool"
            pending_calls[call_id] = {"tool": tool_name, "arguments": arguments}
            frames.append(
                _make_frame(
                    "tool.call",
                    {
                        "sender": tool_sender,
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
        # ── Control tool side effects ─────────────────────────────────────
        # submit_plan_for_approval → awaiting_approval state + plan.status frame
        # finish_workflow          → reset to idle
        if tool_name == "submit_plan_for_approval":
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
        elif tool_name == "finish_workflow":
            session.state = "idle"
            session.last_plan = None
            # Raise a sentinel so the TextEvent planner handler and the
            # RunCompletionEvent fallback both know the workflow is done and
            # must not re-emit plan.status:awaiting_approval even if the
            # planner generates a last narration message with <plan> tags.
            phase_state["workflow_finished"] = True

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

    # ── GroupChatRunChatEvent (speaker selection announcement) ─────────────
    # Fired by GroupChatManager just before the next agent speaks.
    # We use it to track the current speaker so StreamEvent tokens can be
    # attributed to the right agent and filtered accordingly.
    elif isinstance(event, GroupChatRunChatEvent):
        speaker_name = str(getattr(event.content, "speaker", ""))
        phase_state["current_speaker"] = speaker_name
        # No WebSocket frame emitted — internal routing signal only.

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

    # ── StreamEvent (token-by-token content from LLM streaming) ────────────
    elif isinstance(event, StreamEvent):
        # payload = event.content (inner StreamEvent), payload.content = token str
        chunk = str(payload.content or "")
        # Stream tokens from specialists always, and from planner only during
        # Phase 2 (execution) when it is writing the final synthesis reply.
        # During Phase 1 the planner output is shown via plan.proposed /
        # assistant.message structured frames instead.
        current_speaker = phase_state.get("current_speaker", "")
        visible = (
            current_speaker in {"data_specialist", "computation_specialist"}
            or (current_speaker == "planner" and session.state == "executing")
        )
        if chunk and session.state != "awaiting_approval" and visible:
            # Persist to last_answer accumulator so reconnect snapshot works
            if session.last_answer is None:
                session.last_answer = chunk
            else:
                session.last_answer += chunk
            frames.append(
                _make_frame(
                    "assistant.delta",
                    {"sender": current_speaker or "agent", "content": chunk},
                    session_id,
                    turn_id,
                    run_id,
                )
            )

    # ── TextEvent (may contain <plan>, <todo>, sentinels) ─────────────────
    elif isinstance(event, TextEvent):
        content = str(payload.content or "")
        sender = str(getattr(payload, "sender", ""))

        if not content:
            return frames

        # ── Planner messages ─────────────────────────────────────────────
        # Planner is the coordinator: emits plans, todo lists, routing
        # decisions, and the final synthesised answer.
        if sender == "planner":
            # 1. Detect <plan> tags → emit plan.proposed
            plan_match = _PLAN_RE.search(content)
            # Only capture last_plan while the workflow is still in its
            # planning phase.  After finish_workflow fires we must not
            # re-populate last_plan from any planner narration that happens
            # to contain <plan> tags, because RunCompletionEvent would then
            # mis-trigger the HITL fallback.
            if plan_match and not phase_state.get("workflow_finished"):
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
            elif plan_match:
                # Workflow finished — suppress plan.proposed but still let
                # the todo / assistant.message extraction run below.
                pass

            # 2. Detect <todo> tags → emit todo.progress
            todo_match = _TODO_RE.search(content)
            if todo_match:
                todo_text = todo_match.group(1).strip()
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

            # 3. Emit assistant.message for clean synthesised content.
            #    Suppress plan messages since they have dedicated frames.
            #    Control tool calls (submit_plan_for_approval, finish_workflow,
            #    set_routing_target) are detected via ExecutedFunctionEvent —
            #    no sentinel-string scanning needed here.
            suppress_message = plan_match is not None
            if not suppress_message:
                clean = content
                clean = _PLAN_RE.sub("", clean)
                clean = _TODO_RE.sub("", clean)
                clean = _sanitize(clean).strip()

                if clean:
                    session.last_answer = (
                        (session.last_answer or "").split(clean)[0] + clean
                    )
                    frames.append(
                        _make_frame(
                            "assistant.message",
                            {"sender": "planner", "message": clean},
                            session_id,
                            turn_id,
                            run_id,
                        )
                    )

        # ── Specialist messages (data / computation) ─────────────────────
        # Specialists emit a brief narration + [DONE] after each tool call.
        # Strip the [DONE] signal and pass the narration text to the user.
        elif sender in ("data_specialist", "computation_specialist"):
            clean = content.replace("[DONE]", "").strip()
            clean = _sanitize(clean).strip()
            if clean:
                frames.append(
                    _make_frame(
                        "assistant.message",
                        {"sender": sender, "message": clean},
                        session_id,
                        turn_id,
                        run_id,
                    )
                )

        # ── Reviewer messages ────────────────────────────────────────────
        # Reviewer emits [OK] or [RETRY: agent] routing verdicts.
        # These are translated into review.status events; they are never
        # shown verbatim as assistant.message (no user-facing narrative here).
        elif sender == "reviewer":
            if "[OK]" in content:
                frames.append(
                    _make_frame(
                        "review.status",
                        {"status": "ok", "sender": "reviewer"},
                        session_id,
                        turn_id,
                        run_id,
                    )
                )
            elif "[RETRY:" in content:
                frames.append(
                    _make_frame(
                        "review.status",
                        {"status": "retry", "sender": "reviewer", "message": content.strip()},
                        session_id,
                        turn_id,
                        run_id,
                    )
                )
            # All other reviewer text → suppressed (routing noise)

        # tool_executor, user_proxy, chem_manager → suppress

    # ── RunCompletionEvent ────────────────────────────────────────────────
    elif isinstance(event, RunCompletionEvent):
        # Persist turn/run IDs for state snapshot on reconnect
        session.last_turn_id = turn_id
        session.last_run_id = run_id

        # Fallback: planner generated a <plan> block but did NOT call
        # submit_plan_for_approval (e.g., LLM dropped the tool call).
        # Auto-transition so the HITL gate and plan.status frame still fire.
        # Guard: skip if finish_workflow already completed this run —
        # the planner state is "idle" again but we must not re-open HITL.
        if session.state == "idle" and session.last_plan and not phase_state.get("workflow_finished"):
            session.state = "awaiting_approval"
            frames.append(
                _make_frame(
                    "plan.status",
                    {"status": "awaiting_approval", "plan": session.last_plan},
                    session_id,
                    turn_id,
                    run_id,
                )
            )

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
        err_msg = str(payload.error)
        # Filter AG2-internal routing noise.  GroupChatManager's internal
        # speaker name is "chat_manager"; AG2 emits an ErrorEvent with
        # "Invalid group agent name in last message: chat_manager" whenever
        # the manager appears as the last message sender in a round.  This
        # is expected AG2 behaviour and should never surface to the UI.
        _AG2_NOISE = ("Invalid group agent name", "chat_manager")
        if any(token in err_msg for token in _AG2_NOISE):
            return frames  # suppress silently
        frames.append(
            _make_frame(
                "run.failed",
                {"error": err_msg},
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
    phase_state: dict[str, object] = {
        "generated_image": False,
        # Tracks the agent currently speaking (updated by GroupChatRunChatEvent)
        # so StreamEvent tokens can be attributed and filtered by agent role.
        "current_speaker": "",
    }

    # ── Console streaming helpers ──────────────────────────────────────────
    # Print tokens to stdout in real-time so the server terminal shows a
    # typewriter effect.  Uses ANSI colours: white for content, grey for
    # reasoning tokens.  A trailing newline is printed when a non-chunk
    # event arrives so log lines stay clean.
    _console_open = False   # True while we are mid-stream (no trailing \n yet)

    def _console_chunk(text: str, grey: bool = False) -> None:
        nonlocal _console_open
        if not text:
            return
        if grey:
            import sys
            print(f"\033[90m{text}\033[0m", end="", flush=True, file=sys.stderr)
        else:
            print(text, end="", flush=True)
        _console_open = True

    def _console_newline() -> None:
        nonlocal _console_open
        if _console_open:
            print(flush=True)
            _console_open = False

    try:
        async for event in response.events:  # type: ignore[attr-defined]
            # ── Real-time console typewriter output ────────────────────────
            if isinstance(event, ReasoningChunkEvent):
                _console_chunk(event.content, grey=True)
            elif isinstance(event, StreamEvent):
                _console_chunk(str(getattr(event.content, "content", "") or ""))
            else:
                _console_newline()   # close any open streaming line cleanly

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
        err_msg = str(exc)
        # Suppress AG2-internal routing noise — same guard as in _event_to_frames.
        _AG2_NOISE = ("Invalid group agent name", "chat_manager")
        if not any(token in err_msg for token in _AG2_NOISE):
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
    ``awaiting_approval`` (submit_plan_for_approval tool fired) or ``idle``
    (finish_workflow called for a direct answer).  The caller inspects
    ``session.state`` to decide whether to wait for ``plan.approve`` or
    finish the turn.  Phase 1 messages are saved into ``session.prior_messages``
    so Phase 2 has full planning context.
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
        # Save full message history so Phase 2 has planning context
        session.prior_messages = list(await plan_response.messages)
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
        # Save combined history for any subsequent planning turns
        session.prior_messages = list(await exec_response.messages)
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

from __future__ import annotations

import concurrent.futures
import json
import re
from queue import Queue
from typing import TYPE_CHECKING
from uuid import uuid4

from autogen.events.agent_events import (
    ErrorEvent,
    ExecuteFunctionEvent,
    ExecutedFunctionEvent,
    RunCompletionEvent,
    TextEvent,
    ToolCallEvent,
)
from autogen.io.run_response import RunResponseProtocol

from app.api.protocol import EventEnvelope
from app.api.runtime import MultiAgentRunPlan, SpecialistSummary
from app.core.tooling import parse_tool_payload, tool_result_store

if TYPE_CHECKING:
    from app.api.sessions import ChatSession

_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)", re.IGNORECASE)
_DATA_URL_RE = re.compile(r"data:[^\s)]+", re.IGNORECASE)


def _json_loads(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def sanitize_assistant_message(content: str) -> str:
    sanitized = _MARKDOWN_IMAGE_RE.sub("", content)
    sanitized = _DATA_URL_RE.sub("[artifact]", sanitized)
    return sanitized.strip()


def _event_to_frames(
    *,
    event: object,
    session_id: str,
    turn_id: str,
    run_id: str,
    sender: str,
    is_final_phase: bool,
    pending_calls: dict[str, dict[str, object]],
    summaries_out: list[SpecialistSummary],
    phase_state: dict[str, bool],
) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    payload = event.content

    if isinstance(event, ToolCallEvent):
        for tool_call in payload.tool_calls:
            call_id = tool_call.id or f"call_{uuid4().hex}"
            arguments = _json_loads(tool_call.function.arguments)
            tool_name = tool_call.function.name or "unknown_tool"
            pending_calls[call_id] = {"tool": tool_name, "arguments": arguments}
            frames.append(
                EventEnvelope(
                    type="tool.call",
                    session_id=session_id,
                    turn_id=turn_id,
                    run_id=run_id,
                    payload={
                        "sender": sender,
                        "tool_call_id": call_id,
                        "tool": {"name": tool_name},
                        "arguments": arguments,
                    },
                ).to_wire()
            )

    elif isinstance(event, ExecuteFunctionEvent):
        call_id = payload.call_id or f"call_{uuid4().hex}"
        pending_calls[call_id] = {
            "tool": payload.func_name,
            "arguments": payload.arguments or {},
        }

    elif isinstance(event, ExecutedFunctionEvent):
        call_id = payload.call_id or ""
        pending = pending_calls.get(call_id, {})
        tool_name = str(pending.get("tool", payload.func_name))
        result = parse_tool_payload(str(payload.content))
        if result is not None:
            result = tool_result_store.get(result.result_id) or result

        if result is None:
            frames.append(
                EventEnvelope(
                    type="tool.result",
                    session_id=session_id,
                    turn_id=turn_id,
                    run_id=run_id,
                    payload={
                        "sender": sender,
                        "tool_call_id": call_id or None,
                        "tool": {"name": tool_name},
                        "status": "success" if payload.is_exec_success else "error",
                        "summary": str(payload.content),
                        "data": payload.arguments or {},
                        "artifacts": [],
                    },
                ).to_wire()
            )
        else:
            if any(artifact.kind == "image" and artifact.mime_type.startswith("image/") for artifact in result.artifacts):
                phase_state["generated_image"] = True
            frames.append(
                EventEnvelope(
                    type="tool.result",
                    session_id=session_id,
                    turn_id=turn_id,
                    run_id=run_id,
                    payload={
                        "sender": sender,
                        "tool_call_id": call_id or None,
                        "tool": {"name": tool_name},
                        "status": result.status,
                        "summary": result.summary,
                        "data": result.data,
                        "retry_hint": result.retry_hint,
                        "error_code": result.error_code,
                        "artifacts": [artifact.model_dump() for artifact in result.artifacts],
                    },
                ).to_wire()
            )

    elif isinstance(event, TextEvent):
        content = str(payload.content or "").strip()
        if content and payload.sender == sender:
            message = sanitize_assistant_message(content.removesuffix("TERMINATE").strip())
            if message:
                frames.append(
                    EventEnvelope(
                        type="assistant.message",
                        session_id=session_id,
                        turn_id=turn_id,
                        run_id=run_id,
                        payload={"sender": sender, "message": message},
                    ).to_wire()
                )

    elif isinstance(event, RunCompletionEvent):
        summaries_out.append(
            SpecialistSummary(
                label=sender,
                success=True,
                summary=str(payload.summary or ""),
                generated_image=phase_state.get("generated_image", False),
            )
        )
        if is_final_phase:
            frames.append(
                EventEnvelope(
                    type="run.finished",
                    session_id=session_id,
                    turn_id=turn_id,
                    run_id=run_id,
                    payload={"summary": payload.summary, "last_speaker": payload.last_speaker},
                ).to_wire()
            )

    elif isinstance(event, ErrorEvent):
        summaries_out.append(
            SpecialistSummary(label=sender, success=False, summary="", error=str(payload.error))
        )
        if is_final_phase:
            frames.append(
                EventEnvelope(
                    type="run.failed",
                    session_id=session_id,
                    turn_id=turn_id,
                    run_id=run_id,
                    payload={"error": str(payload.error)},
                ).to_wire()
            )

    return frames


def _drain_response(
    *,
    response: RunResponseProtocol,
    session_id: str,
    turn_id: str,
    run_id: str,
    sender: str,
    queue: Queue,
    summaries_out: list[SpecialistSummary],
    is_final_phase: bool,
) -> None:
    pending_calls: dict[str, dict[str, object]] = {}
    phase_state = {"generated_image": False}
    try:
        for event in response.events:
            for frame in _event_to_frames(
                event=event,
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
                sender=sender,
                is_final_phase=is_final_phase,
                pending_calls=pending_calls,
                summaries_out=summaries_out,
                phase_state=phase_state,
            ):
                queue.put(frame)
    except Exception as exc:
        summaries_out.append(SpecialistSummary(label=sender, success=False, summary="", error=str(exc)))
        if is_final_phase:
            queue.put(
                EventEnvelope(
                    type="run.failed",
                    session_id=session_id,
                    turn_id=turn_id,
                    run_id=run_id,
                    payload={"error": f"[{sender}] {exc}"},
                ).to_wire()
            )


def _drain_specialists_parallel(
    *,
    phase2_items: list[tuple[str, RunResponseProtocol]],
    session_id: str,
    turn_id: str,
    run_id: str,
    queue: Queue,
    summaries_out: list[SpecialistSummary],
) -> None:
    frame_buffers: dict[str, list[dict[str, object]]] = {label: [] for label, _ in phase2_items}
    specialist_summaries: dict[str, list[SpecialistSummary]] = {label: [] for label, _ in phase2_items}

    def collect(label: str, response: RunResponseProtocol) -> None:
        pending_calls: dict[str, dict[str, object]] = {}
        phase_state = {"generated_image": False}
        try:
            for event in response.events:
                frame_buffers[label].extend(
                    _event_to_frames(
                        event=event,
                        session_id=session_id,
                        turn_id=turn_id,
                        run_id=run_id,
                        sender=label,
                        is_final_phase=False,
                        pending_calls=pending_calls,
                        summaries_out=specialist_summaries[label],
                        phase_state=phase_state,
                    )
                )
        except Exception as exc:
            specialist_summaries[label].append(
                SpecialistSummary(label=label, success=False, summary="", error=str(exc))
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(phase2_items)) as pool:
        futures = [pool.submit(collect, label, response) for label, response in phase2_items]
        concurrent.futures.wait(futures)

    for label, _ in phase2_items:
        for frame in frame_buffers[label]:
            queue.put(frame)
        summaries_out.extend(specialist_summaries[label])


def stream_multi_agent_run(
    *,
    plan: MultiAgentRunPlan,
    session: ChatSession,
    turn_id: str,
    run_id: str,
    output_queue: Queue,
) -> None:
    all_summaries: list[SpecialistSummary] = []
    session_id = session.session_id

    try:
        if len(plan.phase2_items) == 1:
            label, response = plan.phase2_items[0]
            _drain_response(
                response=response,
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
                sender=label,
                queue=output_queue,
                summaries_out=all_summaries,
                is_final_phase=False,
            )
        elif len(plan.phase2_items) > 1:
            _drain_specialists_parallel(
                phase2_items=plan.phase2_items,
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
                queue=output_queue,
                summaries_out=all_summaries,
            )

        synthesis_response = plan.synthesis_factory(all_summaries)
        _drain_response(
            response=synthesis_response,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            sender="Manager",
            queue=output_queue,
            summaries_out=[],
            is_final_phase=True,
        )
    except Exception as exc:
        output_queue.put(
            EventEnvelope(
                type="run.failed",
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
                payload={"error": str(exc)},
            ).to_wire()
        )
    finally:
        output_queue.put(None)
        session.lock.release()

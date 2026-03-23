"""
Event bridge — translate AG2 events into WebSocket frames.

Architecture v2 changes:
  - _drain_specialists_parallel now uses the shared IO_POOL instead of
    ephemeral per-turn ThreadPoolExecutors.
  - stream_specialists() is the new sync entry point for Phase 2 (called via
    IO_POOL.submit from chat.py).  stream_multi_agent_run() is removed.
  - stream_greeting() accepts agent_models dict instead of a ChatSession.
  - stream_synthesis_async() replaces _stream_synthesis_direct() with a fully
    async implementation using AsyncOpenAI — runs directly in the event loop,
    no Queue needed.
"""

from __future__ import annotations

import asyncio
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

from openai import AsyncOpenAI

from app.api.protocol import EventEnvelope
from app.api.runtime import MultiAgentRunPlan, SpecialistSummary
from app.core.executor import IO_POOL
from app.core.tooling import parse_tool_payload, tool_result_store

if TYPE_CHECKING:
    from fastapi import WebSocket

_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)", re.IGNORECASE)
_DATA_URL_RE = re.compile(r"data:[^\s)]+", re.IGNORECASE)
_TERMINATE = "TERMINATE"
_TERMINATE_LEN = len(_TERMINATE)


def _json_loads(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def sanitize_assistant_message(content: str) -> str:
    """Remove inline image markdown and data URLs. Does NOT strip whitespace.

    Callers in the streaming path rely on newlines being preserved so that
    Markdown headings and lists parse correctly on the frontend.
    """
    sanitized = _MARKDOWN_IMAGE_RE.sub("", content)
    sanitized = _DATA_URL_RE.sub("[artifact]", sanitized)
    return sanitized


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
            if any(
                artifact.kind == "image" and artifact.mime_type.startswith("image/")
                for artifact in result.artifacts
            ):
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
        content = str(payload.content or "")
        if content and payload.sender == sender:
            # Strip only TERMINATE suffix (appears on final chunk); preserve
            # internal whitespace so streaming tokens concatenate correctly.
            message = sanitize_assistant_message(content.removesuffix("TERMINATE"))
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
    """Drain all specialists concurrently using the shared IO_POOL.

    Each specialist's events stream directly into *queue* as they arrive so
    the frontend receives real-time progress without per-turn thread pools.
    Blocks until all specialist futures have resolved.
    """
    specialist_summaries: dict[str, list[SpecialistSummary]] = {label: [] for label, _ in phase2_items}

    def collect(label: str, response: RunResponseProtocol) -> None:
        pending_calls: dict[str, dict[str, object]] = {}
        phase_state = {"generated_image": False}
        try:
            for event in response.events:
                for frame in _event_to_frames(
                    event=event,
                    session_id=session_id,
                    turn_id=turn_id,
                    run_id=run_id,
                    sender=label,
                    is_final_phase=False,
                    pending_calls=pending_calls,
                    summaries_out=specialist_summaries[label],
                    phase_state=phase_state,
                ):
                    queue.put(frame)  # stream immediately, not buffered
        except Exception as exc:
            specialist_summaries[label].append(
                SpecialistSummary(label=label, success=False, summary="", error=str(exc))
            )

    # Use the *shared* IO_POOL (bounded to 16 workers) — no per-turn pools.
    futures = [IO_POOL.submit(collect, label, response) for label, response in phase2_items]
    for future in futures:
        future.result()  # block until all specialists finish

    for label, _ in phase2_items:
        summaries_out.extend(specialist_summaries[label])


# ── Public streaming functions (called from chat.py) ─────────────────────────


def stream_specialists(
    *,
    plan: MultiAgentRunPlan,
    session_id: str,
    turn_id: str,
    run_id: str,
    output_queue: Queue,
    summaries_out: list[SpecialistSummary],
) -> None:
    """Phase 2 entry point — drain all specialists and put None sentinel when done.

    Submitted via ``IO_POOL.submit(stream_specialists, ...)``.  The None
    sentinel signals ``_pump_queue_to_websocket()`` in chat.py to stop and
    return control to the async event loop for Phase 3 (synthesis).
    """
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
                summaries_out=summaries_out,
                is_final_phase=False,
            )
        elif len(plan.phase2_items) > 1:
            _drain_specialists_parallel(
                phase2_items=plan.phase2_items,
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
                queue=output_queue,
                summaries_out=summaries_out,
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


def stream_greeting(
    *,
    agent_models: dict,
    session_id: str,
    turn_id: str,
    run_id: str,
    output_queue: Queue,
) -> None:
    """Generate a greeting from a fresh Manager agent and stream into output_queue.

    Accepts ``agent_models`` dict (not a ChatSession) — the AgentTeam is built
    via ``sessions.run_greeting()`` and garbage-collected on return.
    """
    from app.api.sessions import run_greeting as _run_greeting

    try:
        response = _run_greeting(agent_models)
        _drain_response(
            response=response,
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


async def stream_synthesis_async(
    *,
    synthesis_factory,
    summaries: list[SpecialistSummary],
    websocket: "WebSocket",
    session_id: str,
    turn_id: str,
    run_id: str,
) -> None:
    """Phase 3: stream Manager synthesis reply directly via AsyncOpenAI.

    Replaces _stream_synthesis_direct() + daemon-thread + Queue pattern.
    Runs entirely in the asyncio event loop — no threads, no blocking I/O.

    Uses a rolling tail buffer (len == len("TERMINATE")) so the AG2 sentinel
    word is never emitted mid-stream even when split across chunks.
    """
    synthesis_prompt, system_message, llm_config = synthesis_factory(summaries)
    cfg = llm_config.config_list[0]

    client_kwargs: dict = {"api_key": cfg["api_key"]}
    if "base_url" in cfg:
        client_kwargs["base_url"] = cfg["base_url"]
    client = AsyncOpenAI(**client_kwargs)

    try:
        stream = await client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": synthesis_prompt},
            ],
            stream=True,
        )

        tail = ""
        async for chunk in stream:
            delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if not delta:
                continue
            combined = tail + delta
            safe = combined[:-_TERMINATE_LEN] if len(combined) > _TERMINATE_LEN else ""
            tail = combined[-_TERMINATE_LEN:]
            text = sanitize_assistant_message(safe.replace(_TERMINATE, ""))
            if text:
                await websocket.send_json(
                    EventEnvelope(
                        type="assistant.message",
                        session_id=session_id,
                        turn_id=turn_id,
                        run_id=run_id,
                        payload={"sender": "Manager", "message": text},
                    ).to_wire()
                )

        # Flush remaining tail
        if tail_text := sanitize_assistant_message(tail.replace(_TERMINATE, "")):
            await websocket.send_json(
                EventEnvelope(
                    type="assistant.message",
                    session_id=session_id,
                    turn_id=turn_id,
                    run_id=run_id,
                    payload={"sender": "Manager", "message": tail_text},
                ).to_wire()
            )

    except Exception as exc:
        await websocket.send_json(
            EventEnvelope(
                type="run.failed",
                session_id=session_id,
                turn_id=turn_id,
                run_id=run_id,
                payload={"error": f"[Synthesis] {exc}"},
            ).to_wire()
        )
        return

    await websocket.send_json(
        EventEnvelope(
            type="run.finished",
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            payload={"summary": None, "last_speaker": "Manager"},
        ).to_wire()
    )

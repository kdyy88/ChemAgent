"""
POST /api/chat/stream  — LangGraph-powered Server-Sent Events endpoint.

Replaces the old WebSocket + thread-pool + queue mechanism with a clean
async generator driven by LangGraph's astream_events(version="v2").

SSE event schema
────────────────
Each ``data:`` line carries a JSON object with a ``type`` discriminator:

  type="token"         — streaming text token from an LLM node
  type="node_start"    — a named graph node began executing
  type="node_end"      — a named graph node finished
  type="tool_start"    — an @tool call started
  type="tool_end"      — an @tool call finished with result
  type="artifact"      — a rich artifact (molecule image, descriptor table)
  type="shadow_error"  — Shadow Lab detected an invalid SMILES
  type="done"          — the graph run completed (final event)
  type="error"         — unhandled exception; stream terminates

All events include a session_id and turn_id for client-side state correlation.

Usage
─────
    POST /api/chat/stream
    Content-Type: application/json

    {
      "session_id": "optional-uuid-for-state-continuity",
      "turn_id":    "client-generated-uuid",
      "message":    "计算阿司匹林的 Lipinski 性质，SMILES 为 CC(=O)Oc1ccccc1C(=O)O"
    }

    → text/event-stream

The endpoint is stateless between requests (each POST bootstraps its own
LangGraph state from the message).  Session-level memory (cross-turn context)
can be added later by persisting / rehydrating the messages list via a
LangGraph checkpointer (e.g. SqliteSaver or RedisSaver).
"""

from __future__ import annotations

import json
import traceback
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from app.agents.graph import ChemMVPState, compiled_graph

router = APIRouter()


# ── Request schema ─────────────────────────────────────────────────────────────


class HistoryMessage(BaseModel):
    role: str   # "human" or "assistant"
    content: str


class StreamChatRequest(BaseModel):
    message: str = Field(..., description="用户输入的化学问题或指令")
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    turn_id: str = Field(default_factory=lambda: uuid4().hex)
    active_smiles: str | None = Field(
        default=None,
        description="当前画布上已激活的 SMILES（可选；来自前端状态）",
    )
    interrupt_context: dict | None = Field(
        default=None,
        description="HITL 续研上下文：含 question、called_tools、known_smiles 等",
    )
    history: list[HistoryMessage] = Field(
        default_factory=list,
        description="前序对话轮次消息，按时间正序排列（human/assistant 交替）",
    )


# ── SSE helpers ────────────────────────────────────────────────────────────────

def _sse(payload: dict) -> str:
    """Format a dict as an SSE ``data:`` line with a double-newline terminator."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ── Nodes whose LLM tokens we want to stream to the client ────────────────────

# Nodes whose LLM tokens we stream to the client.
# NOTE: `supervisor` is intentionally excluded — it uses with_structured_output
# which streams routing JSON, not user-facing text.  The `responder` node
# handles direct replies when no tools are needed.
_STREAMING_NODES = {"responder", "researcher", "visualizer", "analyst", "prep"}

# LangGraph node names we surface as lifecycle events to the frontend
_LIFECYCLE_NODES = {"supervisor", "responder", "researcher", "visualizer", "analyst", "prep", "shadow_lab"}


# ── Core generator ─────────────────────────────────────────────────────────────

async def _event_generator(req: StreamChatRequest):
    """Async generator that drives astream_events and yields SSE text chunks."""

    session_id = req.session_id
    turn_id = req.turn_id

    # ── Build initial graph state ─────────────────────────────────────────────
    # Reconstruct prior conversation turns so the graph has full context.
    history_messages = []
    for h in req.history:
        if h.role == "human":
            history_messages.append(HumanMessage(content=h.content))
        elif h.role == "assistant" and h.content.strip():
            history_messages.append(AIMessage(content=h.content))

    initial_state: ChemMVPState = {
        "messages": [*history_messages, HumanMessage(content=req.message)],
        "active_smiles": req.active_smiles,
        "validation_errors": [],
        "artifacts": [],
        "next_node": None,
        "iteration_count": 0,
        "pending_clarification": None,
        "interrupt_options": [],
    }

    # HITL resume: inject the interrupt context so researcher can continue
    if req.interrupt_context:
        ctx = req.interrupt_context
        ctx_lines = [
            f"[HITL 续研] 研究暂停原因：{ctx.get('question', '')}",
            f"已调用工具：{', '.join(ctx.get('called_tools', []))}",
        ]
        if ctx.get("known_smiles"):
            ctx_lines.append(f"已知 SMILES：{ctx['known_smiles']}")
            initial_state["active_smiles"] = ctx["known_smiles"]
        initial_state["pending_clarification"] = ctx.get("question")

    # ── Emit run.started ──────────────────────────────────────────────────────
    yield _sse(
        {
            "type": "run_started",
            "session_id": session_id,
            "turn_id": turn_id,
            "message": req.message,
        }
    )

    try:
        async for event in compiled_graph.astream_events(
            initial_state,
            version="v2",
            config={"configurable": {"session_id": session_id, "turn_id": turn_id}},
        ):
            event_name: str = event["event"]
            node_name: str = event.get("metadata", {}).get("langgraph_node", "")

            # ── 1. Text token streaming ────────────────────────────────────────
            if event_name == "on_chat_model_stream" and node_name in _STREAMING_NODES:
                chunk = event["data"].get("chunk")
                token: str = ""
                if chunk is not None:
                    raw = getattr(chunk, "content", "") or ""
                    # Responses API yields content as a list of content blocks:
                    # [{'type': 'output_text', 'text': '...', 'annotations': [...]}]
                    # Chat Completions API yields a plain string.
                    if isinstance(raw, list):
                        token = "".join(
                            block.get("text", "") if isinstance(block, dict) else str(block)
                            for block in raw
                        )
                    else:
                        token = str(raw) if raw else ""
                if token:
                    yield _sse(
                        {
                            "type": "token",
                            "node": node_name,
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "content": token,
                        }
                    )

            # ── 2. Node lifecycle events ───────────────────────────────────────
            elif event_name == "on_chain_start" and node_name in _LIFECYCLE_NODES:
                yield _sse(
                    {
                        "type": "node_start",
                        "node": node_name,
                        "session_id": session_id,
                        "turn_id": turn_id,
                    }
                )

            elif event_name == "on_chain_end" and node_name in _LIFECYCLE_NODES:
                yield _sse(
                    {
                        "type": "node_end",
                        "node": node_name,
                        "session_id": session_id,
                        "turn_id": turn_id,
                    }
                )

            # ── 3. @tool lifecycle events ──────────────────────────────────────
            elif event_name == "on_tool_start":
                tool_input = event["data"].get("input", {})
                yield _sse(
                    {
                        "type": "tool_start",
                        "tool": event["name"],
                        "input": tool_input,
                        "session_id": session_id,
                        "turn_id": turn_id,
                    }
                )

            elif event_name == "on_tool_end":
                tool_output = event["data"].get("output")
                # Try to parse tool output as JSON for richer client rendering
                parsed_output: dict | str = tool_output
                if isinstance(tool_output, str):
                    try:
                        parsed_output = json.loads(tool_output)
                    except Exception:
                        pass

                yield _sse(
                    {
                        "type": "tool_end",
                        "tool": event["name"],
                        "output": parsed_output,
                        "session_id": session_id,
                        "turn_id": turn_id,
                    }
                )

            # ── 4. Custom artifact events (dispatched from worker nodes) ───────
            elif event_name == "on_custom_event":
                custom_name: str = event.get("name", "")
                custom_data: dict = event.get("data", {})

                if custom_name == "artifact":
                    yield _sse(
                        {
                            "type": "artifact",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            **custom_data,
                        }
                    )

                elif custom_name == "thinking":
                    yield _sse(
                        {
                            "type": "thinking",
                            "text": custom_data.get("text", ""),
                            "iteration": custom_data.get("iteration", 0),
                            "session_id": session_id,
                            "turn_id": turn_id,
                        }
                    )

                elif custom_name == "shadow_lab_error":
                    yield _sse(
                        {
                            "type": "shadow_error",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "smiles": custom_data.get("smiles"),
                            "error": custom_data.get("error"),
                        }
                    )

                elif custom_name == "clarification_request":
                    yield _sse(
                        {
                            "type": "interrupt",
                            "question": custom_data.get("question", ""),
                            "options": custom_data.get("options", []),
                            "called_tools": custom_data.get("called_tools", []),
                            "interrupt_id": uuid4().hex,
                            "session_id": session_id,
                            "turn_id": turn_id,
                        }
                    )

        # ── Emit run.done ─────────────────────────────────────────────────────
        yield _sse(
            {
                "type": "done",
                "session_id": session_id,
                "turn_id": turn_id,
            }
        )

    except Exception as exc:
        tb = traceback.format_exc()
        yield _sse(
            {
                "type": "error",
                "session_id": session_id,
                "turn_id": turn_id,
                "error": str(exc),
                "traceback": tb,
            }
        )


# ── FastAPI route ──────────────────────────────────────────────────────────────


@router.post("/stream")
async def stream_chat(req: StreamChatRequest) -> StreamingResponse:
    """LangGraph-powered SSE chat endpoint.

    Accepts a JSON body and returns a ``text/event-stream`` response driven by
    ``compiled_graph.astream_events(version="v2")``.

    The client reads the stream with ``@microsoft/fetch-event-source`` (or any
    SSE-capable fetch wrapper that supports POST bodies).

    Event types emitted (see module docstring for full schema):
    - ``run_started``  — immediately on connection
    - ``node_start``   — when supervisor / visualizer / analyst / shadow_lab begins
    - ``token``        — individual LLM text tokens (for real-time typewriter UX)
    - ``tool_start``   — when an RDKit @tool starts executing
    - ``tool_end``     — when an RDKit @tool finishes, with parsed JSON output
    - ``artifact``     — molecule image (base64 PNG) or descriptor table (JSON)
    - ``shadow_error`` — Shadow Lab SMILES validation failure details
    - ``node_end``     — when a node finishes
    - ``done``         — graph run complete
    - ``error``        — unhandled exception
    """
    return StreamingResponse(
        _event_generator(req),
        media_type="text/event-stream",
        headers={
            # Prevent proxy buffering (nginx, Caddy, etc.)
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

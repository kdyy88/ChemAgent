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

from app.agents.graph import ChemState, compiled_graph

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


def _sanitize_tool_output_for_sse(tool_name: str, output: dict | str) -> dict | str:
    """Strip bulky artifact payloads from `tool_end` SSE events.

    Rich media and large files are emitted separately through custom `artifact`
    events, so `tool_end` should carry only concise metadata for UI status.
    """
    if not isinstance(output, dict):
        return output

    sanitized = dict(output)
    bulky_keys = {
        "image",
        "structure_image",
        "highlighted_image",
        "sdf_content",
        "pdbqt_content",
    }
    removed = [key for key in bulky_keys if key in sanitized]
    for key in removed:
        sanitized.pop(key, None)

    if tool_name == "tool_convert_format" and isinstance(sanitized.get("output"), str):
        output_text = sanitized["output"]
        if len(output_text) > 500:
            sanitized["output"] = f"已生成 {sanitized.get('output_format', '').upper()} 内容，完整结果通过 artifact 事件发送"
            removed.append("output")

    if removed:
        sanitized["artifact_payloads_removed"] = sorted(set(removed))

    return sanitized


def _thinking_event(
    *,
    text: str,
    session_id: str,
    turn_id: str,
    source: str,
    iteration: int = 0,
    done: bool = True,
) -> str:
    return _sse(
        {
            "type": "thinking",
            "text": text,
            "iteration": iteration,
            "done": done,
            "source": source,
            "session_id": session_id,
            "turn_id": turn_id,
        }
    )


def _node_reasoning_text(node_name: str, event_name: str) -> str | None:
    if node_name == "chem_agent" and event_name == "on_chain_start":
        return "进入智能体推理阶段，正在理解问题并规划下一步。"
    if node_name == "tools_executor" and event_name == "on_chain_start":
        return "进入工具执行阶段，开始调用化学工具获取中间结果。"
    if node_name == "tools_executor" and event_name == "on_chain_end":
        return "工具执行完成，正在把结果返回给智能体继续整合。"
    if node_name == "chem_agent" and event_name == "on_chain_end":
        return "本轮智能体推理完成，准备输出最终结论。"
    return None


def _tool_reasoning_text(tool_name: str, stage: str, output: dict | str | None = None) -> str:
    pretty_name = tool_name.replace("tool_", "")
    label_map = {
        "validate_smiles": "校验 SMILES",
        "strip_salts": "去除盐和溶剂",
        "pubchem_lookup": "PubChem 检索",
        "compute_descriptors": "计算分子描述符",
        "compute_mol_properties": "计算分子性质",
        "substructure_match": "子结构匹配",
        "murcko_scaffold": "提取 Murcko Scaffold",
        "render_smiles": "渲染二维结构图",
        "build_3d_conformer": "生成三维构象",
        "prepare_pdbqt": "准备 PDBQT 文件",
        "convert_format": "格式转换",
        "ask_human": "请求用户澄清",
        "web_search": "联网搜索",
    }
    label = label_map.get(pretty_name, pretty_name)

    if stage == "start":
        return f"正在调用工具：{label}。"

    if isinstance(output, dict):
        message = str(output.get("message", "")).strip()
        if message:
            return f"工具完成：{label}。{message}"

    return f"工具完成：{label}。"


# ── Nodes whose LLM tokens we want to stream to the client ────────────────────

# Nodes whose LLM tokens we stream to the client.
_STREAMING_NODES = {"chem_agent"}

# LangGraph node names we surface as lifecycle events to the frontend
_LIFECYCLE_NODES = {"chem_agent", "tools_executor"}


def _extract_stream_text(raw: object, chunk: object) -> tuple[str, str]:
    """Extract assistant token text and model reasoning text from stream chunks.

    Supports common OpenAI/Responses, Anthropic, and compatibility payload shapes.
    Returns ``(token_text, reasoning_text)``.
    """
    token_parts: list[str] = []
    reasoning_parts: list[str] = []

    def _append_text(target: list[str], value: object) -> None:
        if isinstance(value, str) and value:
            target.append(value)

    if isinstance(raw, str):
        token_parts.append(raw)
    elif isinstance(raw, dict):
        block_type = str(raw.get("type", "")).lower()
        if block_type in {"reasoning", "thinking"}:
            summary = raw.get("summary")
            if isinstance(summary, list):
                for item in summary:
                    if isinstance(item, dict):
                        _append_text(reasoning_parts, item.get("text"))
                    else:
                        _append_text(reasoning_parts, item)
            else:
                _append_text(reasoning_parts, summary)
            _append_text(reasoning_parts, raw.get("text"))
            _append_text(reasoning_parts, raw.get("thinking"))
        elif block_type in {"text", "output_text"}:
            _append_text(token_parts, raw.get("text"))
        elif block_type == "message":
            msg_content = raw.get("content", [])
            if isinstance(msg_content, list):
                for c in msg_content:
                    if isinstance(c, dict):
                        _append_text(token_parts, c.get("text"))
                    else:
                        _append_text(token_parts, c)
            else:
                _append_text(token_parts, msg_content)
        else:
            _append_text(token_parts, raw.get("text"))
            _append_text(reasoning_parts, raw.get("reasoning"))
    elif isinstance(raw, list):
        for block in raw:
            if isinstance(block, dict):
                block_type = str(block.get("type", "")).lower()

                if block_type == "reasoning":
                    summary = block.get("summary", [])
                    if isinstance(summary, list):
                        for s in summary:
                            if isinstance(s, dict):
                                _append_text(reasoning_parts, s.get("text"))
                            else:
                                _append_text(reasoning_parts, s)
                    elif isinstance(summary, str):
                        _append_text(reasoning_parts, summary)
                    _append_text(reasoning_parts, block.get("text"))

                elif block_type == "message":
                    msg_content = block.get("content", [])
                    if isinstance(msg_content, list):
                        for c in msg_content:
                            if isinstance(c, dict):
                                _append_text(token_parts, c.get("text"))
                            else:
                                _append_text(token_parts, c)
                    elif isinstance(msg_content, str):
                        _append_text(token_parts, msg_content)

                elif block_type in {"text", "output_text"}:
                    _append_text(token_parts, block.get("text"))

                elif block_type == "thinking":
                    _append_text(reasoning_parts, block.get("thinking"))
                    _append_text(reasoning_parts, block.get("text"))

            else:
                _append_text(token_parts, block)

    additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
    if isinstance(additional_kwargs, dict):
        _append_text(reasoning_parts, additional_kwargs.get("reasoning_content"))
        _append_text(reasoning_parts, additional_kwargs.get("thinking"))
        _append_text(reasoning_parts, additional_kwargs.get("reasoning"))

    return "".join(token_parts), "".join(reasoning_parts)


# ── Core generator ─────────────────────────────────────────────────────────────

async def _event_generator(req: StreamChatRequest):
    """Async generator that drives astream_events and yields SSE text chunks."""

    session_id = req.session_id
    turn_id = req.turn_id
    llm_reasoning_emitted = False

    # ── Build initial graph state ─────────────────────────────────────────────
    # Reconstruct prior conversation turns so the graph has full context.
    history_messages = []
    for h in req.history:
        if h.role == "human":
            history_messages.append(HumanMessage(content=h.content))
        elif h.role == "assistant" and h.content.strip():
            history_messages.append(AIMessage(content=h.content))

    initial_state: ChemState = {
        "messages": [*history_messages, HumanMessage(content=req.message)],
        "active_smiles": req.active_smiles,
        "artifacts": [],
    }

    # HITL resume: inject the interrupt context so the unified agent can continue.
    if req.interrupt_context:
        ctx = req.interrupt_context
        ctx_lines = [
            f"[HITL 续研] 研究暂停原因：{ctx.get('question', '')}",
            f"已调用工具：{', '.join(ctx.get('called_tools', []))}",
        ]
        if ctx.get("known_smiles"):
            ctx_lines.append(f"已知 SMILES：{ctx['known_smiles']}")
            initial_state["active_smiles"] = ctx["known_smiles"]
        initial_state["messages"].insert(-1, HumanMessage(content="\n".join(ctx_lines)))

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
                if chunk is not None:
                    raw = getattr(chunk, "content", "") or ""
                    token, thinking_token = _extract_stream_text(raw, chunk)

                    # 独立推流：思考过程
                    if thinking_token:
                        llm_reasoning_emitted = True
                        yield _thinking_event(
                            text=thinking_token,
                            iteration=0,
                            session_id=session_id,
                            turn_id=turn_id,
                            source="llm_reasoning",
                            done=False,
                        )

                    # 独立推流：最终回答
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

            elif event_name == "on_chat_model_end" and node_name in _STREAMING_NODES:
                output_msg = event.get("data", {}).get("output")
                # Some providers stream reasoning token-by-token and also include a
                # final aggregated reasoning block at model end. Emit the end block
                # only when stream phase had no reasoning to avoid duplicate panels.
                if output_msg is not None and not llm_reasoning_emitted:
                    raw = getattr(output_msg, "content", "") or ""
                    _, thinking_token = _extract_stream_text(raw, output_msg)
                    if thinking_token:
                        llm_reasoning_emitted = True
                        yield _thinking_event(
                            text=thinking_token,
                            iteration=0,
                            session_id=session_id,
                            turn_id=turn_id,
                            source="llm_reasoning",
                            done=True,
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
                thinking_text = _node_reasoning_text(node_name, event_name)
                if thinking_text:
                    yield _thinking_event(
                        text=thinking_text,
                        session_id=session_id,
                        turn_id=turn_id,
                        source=node_name,
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
                thinking_text = _node_reasoning_text(node_name, event_name)
                if thinking_text:
                    yield _thinking_event(
                        text=thinking_text,
                        session_id=session_id,
                        turn_id=turn_id,
                        source=node_name,
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
                yield _thinking_event(
                    text=_tool_reasoning_text(event["name"], "start"),
                    session_id=session_id,
                    turn_id=turn_id,
                    source="tools_executor",
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

                parsed_output = _sanitize_tool_output_for_sse(event["name"], parsed_output)

                yield _sse(
                    {
                        "type": "tool_end",
                        "tool": event["name"],
                        "output": parsed_output,
                        "session_id": session_id,
                        "turn_id": turn_id,
                    }
                )
                yield _thinking_event(
                    text=_tool_reasoning_text(event["name"], "end", parsed_output),
                    session_id=session_id,
                    turn_id=turn_id,
                    source="tools_executor",
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
                    yield _thinking_event(
                        text=custom_data.get("text", ""),
                        iteration=custom_data.get("iteration", 0),
                        session_id=session_id,
                        turn_id=turn_id,
                        source=custom_data.get("source", "chem_agent"),
                        done=custom_data.get("done", True),
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
        if not llm_reasoning_emitted:
            yield _thinking_event(
                text=(
                    "当前模型或网关未返回原生 reasoning 内容。"
                    "如需显示模型推理摘要，请使用支持 reasoning summary 的模型（例如 GPT-5 系列）并在环境变量中设置 OPENAI_MODEL。"
                ),
                session_id=session_id,
                turn_id=turn_id,
                source="llm_reasoning",
                done=True,
            )

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
    - ``node_start``   — when chem_agent / tools_executor begins
    - ``token``        — individual LLM text tokens (for real-time typewriter UX)
    - ``tool_start``   — when a tool starts executing
    - ``tool_end``     — when a tool finishes, with parsed JSON output
    - ``artifact``     — molecule image (base64 PNG) or descriptor table (JSON)
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

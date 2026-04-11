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
    type="task_update"   — planner/task execution progress update
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

The endpoint is session-aware across requests by persisting LangGraph state
through a checkpointer.  The frontend `session_id` is mapped directly to the
LangGraph `thread_id`, so follow-up turns can resume from the latest saved
checkpoint without re-sending the full conversation transcript.
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from app.domain.schemas.agent import ChemState
from app.agents.runtime import get_compiled_graph, has_persisted_session

router = APIRouter()
logger = logging.getLogger(__name__)

_BULKY_TOOL_OUTPUT_KEYS = frozenset({
    "image",
    "structure_image",
    "highlighted_image",
    "sdf_content",
    "pdbqt_content",
})
_SILENT_TOOL_NAMES = frozenset({"tool_update_task_status"})

_NODE_REASONING_MESSAGES: dict[tuple[str, str], str] = {
    ("task_router", "on_chain_start"): "正在快速判断这次请求是否需要显式任务规划...",
    ("task_router", "on_chain_end"): "复杂度判断完成。",
    ("planner_node", "on_chain_start"): "检测到复杂任务，正在生成可执行任务清单...",
    ("planner_node", "on_chain_end"): "任务清单已生成，准备进入执行阶段。",
    ("chem_agent", "on_chain_start"): "进入智能体大脑，正在评估当前信息并规划下一步行动...",
    ("chem_agent", "on_chain_end"): "智能体本轮思考完毕。",
    ("tools_executor", "on_chain_start"): "准备转入工具执行流水线...",
    ("tools_executor", "on_chain_end"): "工具调用链执行完毕，正在将实验数据交回给智能体大脑。",
}

_TOOL_LABELS: dict[str, str] = {
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
    "update_task_status": "更新任务状态",
}

_DEFAULT_GRAPH_RECURSION_LIMIT = 60


def _load_debug_env_once() -> None:
    """Load .env files so debug toggles are visible in this module too."""
    candidates = [
        Path(__file__).resolve().parents[2] / ".env",  # backend/.env
        Path(__file__).resolve().parents[3] / ".env",  # project-root/.env
        Path.cwd() / ".env",
    ]
    for env_file in candidates:
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=False)


_load_debug_env_once()


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _graph_recursion_limit() -> int:
    raw = os.environ.get("CHEMAGENT_GRAPH_RECURSION_LIMIT", "").strip()
    if not raw:
        return _DEFAULT_GRAPH_RECURSION_LIMIT
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_GRAPH_RECURSION_LIMIT
    return max(25, value)


def _preview(value: object, max_len: int = 1200) -> str:
    """Best-effort compact preview for debug logs."""
    try:
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
    except Exception:
        text = repr(value)
    if len(text) > max_len:
        return text[:max_len] + "...<truncated>"
    return text


def _debug_reasoning_payload(stage: str, node_name: str, message_obj: object) -> None:
    """Emit raw reasoning-related payloads when DEBUG_REASONING_RAW is enabled."""
    if not _env_truthy("DEBUG_REASONING_RAW", False):
        return

    raw_content = getattr(message_obj, "content", None)
    additional_kwargs = getattr(message_obj, "additional_kwargs", None)

    log_line = (
        "[reasoning-debug] "
        f"stage={stage} "
        f"node={node_name} "
        f"content_type={type(raw_content).__name__ if raw_content is not None else 'None'} "
        f"additional_keys={list(additional_kwargs.keys()) if isinstance(additional_kwargs, dict) else None} "
        f"content_preview={_preview(raw_content)} "
        f"additional_preview={_preview(additional_kwargs)}"
    )
    logger.warning(log_line)
    print(log_line, flush=True)


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
        description="LangGraph 原生 HITL 恢复上下文；至少包含 interrupt_id",
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
    removed = [key for key in _BULKY_TOOL_OUTPUT_KEYS if key in sanitized]
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
    category: str | None = None,
    importance: str = "high",
    group_key: str | None = None,
) -> str:
    return _sse(
        {
            "type": "thinking",
            "text": text,
            "iteration": iteration,
            "done": done,
            "source": source,
            "category": category,
            "importance": importance,
            "group_key": group_key,
            "session_id": session_id,
            "turn_id": turn_id,
        }
    )


def _event_payload(event_type: str, session_id: str, turn_id: str, **data: Any) -> dict[str, Any]:
    return {
        "type": event_type,
        "session_id": session_id,
        "turn_id": turn_id,
        **data,
    }


def _event_sse(event_type: str, session_id: str, turn_id: str, **data: Any) -> str:
    return _sse(_event_payload(event_type, session_id, turn_id, **data))


def _node_reasoning_text(node_name: str, event_name: str) -> str | None:
    return _NODE_REASONING_MESSAGES.get((node_name, event_name))


def _is_primary_node_lifecycle_event(event: dict[str, Any], node_name: str) -> bool:
    """Return True only for the top-level LangGraph node lifecycle event.

    LangGraph v2 event streaming propagates the parent ``langgraph_node`` into
    internal wrapper runs like ``RunnableSequence``, ``RunnableLambda``, and
    branch routers such as ``route_from_router``. Those nested runs are not real
    graph-node re-entries, but they currently look identical to the frontend if
    we key only on ``metadata.langgraph_node``. The actual node run keeps its
    own name equal to the graph node name, so that is the stable discriminator.
    """
    return event.get("name") == node_name


def _tool_reasoning_text(tool_name: str, stage: str, payload: dict | str | None = None) -> str:
    pretty_name = tool_name.replace("tool_", "")
    label = _TOOL_LABELS.get(pretty_name, pretty_name)

    if stage == "start":
        return f"正在调用：{label}"

    if stage == "end":
        if isinstance(payload, dict) and "error" in payload:
            return f"{label}失败：{payload['error']}"
        return f"{label}已完成"

    return f"工具完成：{label}。"


def _should_surface_tool(tool_name: str) -> bool:
    return tool_name not in _SILENT_TOOL_NAMES


# ── Nodes whose LLM tokens we want to stream to the client ────────────────────

# Nodes whose LLM tokens we stream to the client.
_STREAMING_NODES = {"chem_agent"}

# LangGraph node names we surface as lifecycle events to the frontend
_LIFECYCLE_NODES = {"task_router", "planner_node", "chem_agent", "tools_executor"}


def _parse_tool_output(tool_output: Any) -> dict | str:
    if isinstance(tool_output, str):
        try:
            return json.loads(tool_output)
        except Exception:
            return tool_output
    return tool_output


def _build_custom_event_handlers(
    *,
    session_id: str,
    turn_id: str,
) -> dict[str, Callable[[dict[str, Any]], str]]:
    return {
        "artifact": lambda data: _event_sse("artifact", session_id, turn_id, **data),
        "thinking": lambda data: _thinking_event(
            text=data.get("text", ""),
            iteration=data.get("iteration", 0),
            session_id=session_id,
            turn_id=turn_id,
            source=data.get("source", "chem_agent"),
            done=data.get("done", True),
            category=data.get("category"),
            importance=data.get("importance", "high"),
            group_key=data.get("group_key"),
        ),
        "task_update": lambda data: _event_sse(
            "task_update",
            session_id,
            turn_id,
            tasks=data.get("tasks", []),
            source=data.get("source", "tools_executor"),
        ),
        "shadow_lab_error": lambda data: _event_sse(
            "shadow_error",
            session_id,
            turn_id,
            smiles=data.get("smiles"),
            error=data.get("error"),
        ),
    }


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
    graph = get_compiled_graph()
    graph_config = {
        "configurable": {"thread_id": session_id, "session_id": session_id, "turn_id": turn_id},
        "recursion_limit": _graph_recursion_limit(),
    }
    has_persisted_state = await has_persisted_session(session_id)
    llm_reasoning_emitted = False
    custom_event_handlers = _build_custom_event_handlers(session_id=session_id, turn_id=turn_id)

    if req.interrupt_context and req.interrupt_context.get("interrupt_id") and not has_persisted_state:
        yield _event_sse(
            "error",
            session_id,
            turn_id,
            error="Cannot resume interruption because no persisted LangGraph session was found.",
        )
        return

    # ── Build initial graph state ─────────────────────────────────────────────
    # Legacy fallback: only replay client-sent history when this session has no
    # saved checkpoints yet, so persisted threads avoid prompt inflation.
    history_messages = []
    if not has_persisted_state:
        for h in req.history:
            if h.role == "human":
                history_messages.append(HumanMessage(content=h.content))
            elif h.role == "assistant" and h.content.strip():
                history_messages.append(AIMessage(content=h.content))

    messages = [*history_messages, HumanMessage(content=req.message)]
    initial_state: ChemState = {
        "messages": messages,
        "artifacts": [],
        "tasks": [],
        "is_complex": False,
    }

    if req.active_smiles:
        initial_state["active_smiles"] = req.active_smiles

    graph_input: ChemState | Command = initial_state
    if req.interrupt_context and req.interrupt_context.get("interrupt_id"):
        graph_input = Command(resume={req.interrupt_context["interrupt_id"]: req.message})

    # ── Emit run.started ──────────────────────────────────────────────────────
    yield _sse(
        _event_payload("run_started", session_id, turn_id, message=req.message)
    )

    try:
        async for event in graph.astream_events(
            graph_input,
            version="v2",
            config=graph_config,
        ):
            event_name: str = event["event"]
            node_name: str = event.get("metadata", {}).get("langgraph_node", "")

            # ── 1. Text token streaming ────────────────────────────────────────
            if event_name == "on_chat_model_stream" and node_name in _STREAMING_NODES:
                chunk = event["data"].get("chunk")
                if chunk is not None:
                    _debug_reasoning_payload("stream", node_name, chunk)
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
                            category="llm",
                            importance="high",
                            group_key="llm_reasoning",
                        )

                    # 独立推流：最终回答
                    if token:
                        yield _event_sse("token", session_id, turn_id, node=node_name, content=token)

            elif event_name == "on_chat_model_end" and node_name in _STREAMING_NODES:
                output_msg = event.get("data", {}).get("output")
                # Some providers stream reasoning token-by-token and also include a
                # final aggregated reasoning block at model end. Emit the end block
                # only when stream phase had no reasoning to avoid duplicate panels.
                if output_msg is not None and not llm_reasoning_emitted:
                    _debug_reasoning_payload("end", node_name, output_msg)
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
                            category="llm",
                            importance="high",
                            group_key="llm_reasoning",
                        )

            # ── 2. Node lifecycle events ───────────────────────────────────────
            elif (
                event_name == "on_chain_start"
                and node_name in _LIFECYCLE_NODES
                and _is_primary_node_lifecycle_event(event, node_name)
            ):
                yield _event_sse("node_start", session_id, turn_id, node=node_name)
                thinking_text = _node_reasoning_text(node_name, event_name)
                if thinking_text:
                    yield _thinking_event(
                        text=thinking_text,
                        session_id=session_id,
                        turn_id=turn_id,
                        source=node_name,
                        category="node",
                        importance="low",
                        group_key=node_name,
                    )

            elif (
                event_name == "on_chain_end"
                and node_name in _LIFECYCLE_NODES
                and _is_primary_node_lifecycle_event(event, node_name)
            ):
                yield _event_sse("node_end", session_id, turn_id, node=node_name)
                thinking_text = _node_reasoning_text(node_name, event_name)
                if thinking_text:
                    yield _thinking_event(
                        text=thinking_text,
                        session_id=session_id,
                        turn_id=turn_id,
                        source=node_name,
                        category="node",
                        importance="low",
                        group_key=node_name,
                    )

            # ── 3. @tool lifecycle events ──────────────────────────────────────
            elif event_name == "on_tool_start":
                if not _should_surface_tool(event["name"]):
                    continue

                tool_input = event["data"].get("input", {})
                yield _event_sse("tool_start", session_id, turn_id, tool=event["name"], input=tool_input)
                yield _thinking_event(
                    text=_tool_reasoning_text(event["name"], "start", tool_input),
                    session_id=session_id,
                    turn_id=turn_id,
                    source="tools_executor",
                    category="tool",
                    importance="high",
                    group_key=event["name"],
                )

            elif event_name == "on_tool_end":
                if not _should_surface_tool(event["name"]):
                    continue

                tool_output = event["data"].get("output")
                parsed_output = _sanitize_tool_output_for_sse(
                    event["name"],
                    _parse_tool_output(tool_output),
                )

                yield _event_sse(
                    "tool_end",
                    session_id,
                    turn_id,
                    tool=event["name"],
                    output=parsed_output,
                )
                if isinstance(parsed_output, dict) and "error" in parsed_output:
                    yield _thinking_event(
                        text=_tool_reasoning_text(event["name"], "end", parsed_output),
                        session_id=session_id,
                        turn_id=turn_id,
                        source="tools_executor",
                        category="error",
                        importance="high",
                        group_key=event["name"],
                    )

            # ── 4. Custom artifact events (dispatched from worker nodes) ───────
            elif event_name == "on_custom_event":
                custom_name: str = event.get("name", "")
                custom_data: dict = event.get("data", {})
                handler = custom_event_handlers.get(custom_name)
                if handler is not None:
                    yield handler(custom_data)

        # ── Emit run.done ─────────────────────────────────────────────────────
        snapshot = await graph.aget_state(graph_config)
        if snapshot.interrupts:
            pending_interrupt = snapshot.interrupts[0]
            pending_value = pending_interrupt.value if isinstance(pending_interrupt.value, dict) else {}
            yield _event_sse(
                "interrupt",
                session_id,
                turn_id,
                question=str(pending_value.get("question", "")),
                options=list(pending_value.get("options", [])),
                called_tools=list(pending_value.get("called_tools", [])),
                known_smiles=pending_value.get("known_smiles"),
                interrupt_id=pending_interrupt.id,
            )
            return

        checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
        yield _event_sse("done", session_id, turn_id, checkpoint_id=checkpoint_id)

    except Exception as exc:
        tb = traceback.format_exc()
        # Provide a more user-friendly message for common network errors
        # (e.g. LLM API / proxy closing chunked connection prematurely).
        err_str = str(exc)
        if "incomplete chunked read" in err_str or "peer closed connection" in err_str:
            err_str = "与 LLM 服务的连接被意外中断（incomplete chunked read）。请检查网络连接或 API 服务状态后重试。"
        yield _event_sse("error", session_id, turn_id, error=err_str, traceback=tb)


# ── FastAPI route ──────────────────────────────────────────────────────────────


@router.post("/stream")
async def stream_chat(req: StreamChatRequest) -> StreamingResponse:
    """LangGraph-powered SSE chat endpoint.

    Accepts a JSON body and returns a ``text/event-stream`` response driven by
    ``graph.astream_events(version="v2")``.

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

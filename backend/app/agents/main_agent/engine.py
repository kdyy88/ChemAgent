"""ChemSessionEngine — 双层生成器架构
=====================================

外层 (submit_message)：生命周期管理、Artifact 指针拦截、错误扣留与自愈重试、SSE 格式化输出。
内层 (_graph_query_loop)：纯 LangGraph 图计算，将底层事件解析为标准化 dict。

控制面 / 数据面分离
────────────────────
- **控制面**：流向前端的 SSE 事件流；只携带轻量级元数据与工件指针。
- **数据面**：Redis artifact store（``app.domain.store.artifact_store``）；挂载大体积 SDF/PDB/图像等计算结果，
  避免原始内容撑爆 LLM 上下文窗口或 SSE 帧。

错误扣留 (Error Withholding)
────────────────────────────
识别可自愈的化学底层错误（价键非法、SMILES 解析失败等），在前端感知到该错误
之前，由引擎自动注入修正提示并触发重试，而非直接将原始异常抛给用户。
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from pathlib import Path
from typing import Any, AsyncGenerator
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import Command

from app.agents.main_agent.runtime import get_compiled_graph, has_persisted_session
from app.agents.nodes.agent import LlmCallTimeoutError
from app.domain.schemas.agent import ChemState, MoleculeNode
from app.domain.store.artifact_store import store_engine_artifact
from app.domain.store.plan_store import update_plan_file
from app.agents.main_agent.engine_sse import (
    _ARTIFACT_COLLAPSE_KEYS,
    _ChemRetrySignal,
    _LIFECYCLE_NODES,
    _NODE_REASONING_MESSAGES,
    _SILENT_TOOL_NAMES,
    _STREAMING_NODES,
    _SUB_AGENT_NODE_PREFIX,
    _TOOL_LABELS,
    _WITHHELD_ERROR_KEYWORDS,
    _extract_stream_text,
    _parse_tool_output,
    _preview,
    _sanitize_tool_output,
)

logger = logging.getLogger(__name__)

_DEFAULT_GRAPH_RECURSION_LIMIT = 60

# ── Environment helpers ────────────────────────────────────────────────────────


def _load_debug_env_once() -> None:
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


# ── Engine ─────────────────────────────────────────────────────────────────────


import hashlib


def _seed_state_from_smiles(
    active_smiles: str | None,
) -> tuple[dict, dict]:
    """Derive initial viewport + molecule_tree from a seed SMILES supplied by the frontend.

    Returns (viewport_dict, molecule_tree_dict). When active_smiles is None or empty
    both dicts are empty / unpopulated so the LLM starts with a blank IDE workspace.
    """
    if not active_smiles:
        return {"focused_artifact_ids": []}, {}
    smiles_hash = hashlib.md5(active_smiles.encode()).hexdigest()[:8]
    artifact_id = f"mol_seed_{smiles_hash}"
    node: MoleculeNode = {
        "artifact_id": artifact_id,
        "smiles": active_smiles,
        "status": "staged",
    }
    return {"focused_artifact_ids": [artifact_id]}, {artifact_id: node}


class ChemSessionEngine:
    """ChemAgent 双层会话引擎。

    **外层** (``submit_message``)
        驱动单次用户交互的全生命周期：
        - 构建 LangGraph 初始状态
        - 拦截大体积工件 → Artifact 指针（控制面 / 数据面隔离）
        - 扣留可自愈化学错误 → 注入修正提示 → 自动重试
        - 将 dict 事件序列化为 SSE 文本帧

    **内层** (``_graph_query_loop``)
        纯粹的 LangGraph 图执行，将 ``astream_events(version="v2")``
        底层事件解析为标准化 Python dict，不含任何 SSE 格式化。
    """

    MAX_RETRIES = 3

    def __init__(self, session_id: str, turn_id: str) -> None:
        self.session_id = session_id
        self.turn_id = turn_id
        # Per-call flag; reset at the top of each submit_message invocation.
        self._llm_reasoning_emitted: bool = False

    # ── SSE serialization helpers ──────────────────────────────────────────────

    def _sse(self, payload: dict) -> str:
        """Serialize a dict to an SSE ``data:`` line."""
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _event_payload(self, event_type: str, **data: Any) -> dict[str, Any]:
        return {
            "type": event_type,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            **data,
        }

    def _thinking_dict(
        self,
        *,
        text: str,
        source: str,
        iteration: int = 0,
        done: bool = True,
        category: str | None = None,
        importance: str = "high",
        group_key: str | None = None,
    ) -> dict:
        return {
            "type": "thinking",
            "text": text,
            "iteration": iteration,
            "done": done,
            "source": source,
            "category": category,
            "importance": importance,
            "group_key": group_key,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
        }

    def _usage_dict(
        self,
        *,
        node: str,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
    ) -> dict[str, Any]:
        return {
            "type": "usage",
            "node": node,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
        }

    # ── Outer generator ────────────────────────────────────────────────────────

    async def submit_message(
        self,
        *,
        message: str,
        history: list[Any] | None = None,
        model: str | None = None,
        active_smiles: str | None = None,
        interrupt_context: dict | None = None,
        skills_enabled: bool = False,
    ) -> AsyncGenerator[str, None]:
        """【外层生成器】驱动单次用户交互的全生命周期。

        Parameters
        ----------
        message:
            用户当前轮次的自然语言输入。
        history:
            前序对话轮次列表，每项需具有 ``.role`` 和 ``.content`` 属性。
            当 LangGraph 存在持久化检查点时此参数被忽略。
        active_smiles:
            前端画布上当前激活的 SMILES（可选）。
        interrupt_context:
            LangGraph HITL 恢复上下文；需含 ``interrupt_id``（可选）。
        """
        self._llm_reasoning_emitted = False

        session_id = self.session_id
        turn_id = self.turn_id

        has_persisted_state = await has_persisted_session(session_id)

        # Guard: cannot resume an interrupt that has no saved checkpoint.
        if (
            interrupt_context
            and interrupt_context.get("interrupt_id")
            and not has_persisted_state
        ):
            yield self._sse(
                self._event_payload(
                    "error",
                    error="Cannot resume interruption because no persisted LangGraph session was found.",
                )
            )
            return

        # Build conversation history (only when no persisted state exists).
        history_messages: list = []
        if not has_persisted_state and history:
            for h in history:
                if h.role == "human":
                    history_messages.append(HumanMessage(content=h.content))
                elif h.role == "assistant" and h.content.strip():
                    history_messages.append(AIMessage(content=h.content))

        initial_messages = [*history_messages, HumanMessage(content=message)]

        _viewport, _molecule_tree = _seed_state_from_smiles(active_smiles)
        initial_state: ChemState = {
            "messages": initial_messages,
            "selected_model": model,
            "artifacts": [],
            "viewport": _viewport,
            "molecule_tree": _molecule_tree,
            "scratchpad": {},
            "tasks": [],
            "is_complex": False,
            "evidence_revision": 0,
            "sub_agent_result": None,
            "active_subtasks": {},
            "active_subtask_id": None,
            "subtask_control": None,
            "skills_enabled": skills_enabled,
        }

        # Resolve graph input: normal turn vs. HITL resume.
        graph_input: ChemState | Command = initial_state
        if interrupt_context and interrupt_context.get("interrupt_id"):
            graph_input = Command(
                resume={interrupt_context["interrupt_id"]: message}
            )

        graph_config = {
            "configurable": {
                "thread_id": session_id,
                "session_id": session_id,
                "turn_id": turn_id,
            },
            "recursion_limit": _graph_recursion_limit(),
        }

        yield self._sse(self._event_payload("run_started", message=message))

        current_retry = 0
        active_graph_input: Any = graph_input

        while current_retry <= self.MAX_RETRIES:
            try:
                async for event_dict in self._graph_query_loop(
                    active_graph_input, graph_config
                ):
                    # ── Interceptor 1: Artifact Pointer (data-plane isolation) ─
                    if event_dict.get("type") == "tool_end":
                        event_dict = await self._intercept_and_collapse_artifact(event_dict)

                    # ── Interceptor 2: Error Withholding (auto self-correction) ─
                    withheld = self._withheld_error_message(event_dict)
                    if withheld is not None:
                        logger.warning("触发错误扣留 (error withholding): %s", withheld)
                        raise _ChemRetrySignal(
                            error_msg=withheld,
                            new_messages=[
                                SystemMessage(
                                    content=(
                                        f"执行失败: {withheld}。"
                                        "请检查参数并重新尝试。"
                                    )
                                )
                            ],
                        )

                    yield self._sse(event_dict)

                # Loop exited normally — we're done.
                break

            except _ChemRetrySignal as retry_sig:
                current_retry += 1
                if current_retry > self.MAX_RETRIES:
                    yield self._sse(
                        self._event_payload(
                            "error",
                            error=(
                                f"已达最大重试次数 ({self.MAX_RETRIES})，"
                                f"最后错误: {retry_sig.error_msg}"
                            ),
                        )
                    )
                    return

                yield self._sse(
                    self._thinking_dict(
                        text=f"检测到执行错误，正在进行自我修正，第 {current_retry} 次尝试...",
                        source="engine",
                        category="system",
                        importance="high",
                    )
                )
                # Only push the correction system message in the next turn;
                # LangGraph state already holds the full prior conversation.
                active_graph_input = {"messages": retry_sig.new_messages}
                self._llm_reasoning_emitted = False

            except LlmCallTimeoutError as exc:
                current_retry += 1
                if current_retry > self.MAX_RETRIES:
                    yield self._sse(
                        self._event_payload(
                            "error",
                            error=(
                                f"LLM 调用连续超时，已达最大重试次数 ({self.MAX_RETRIES})。"
                                f"最后错误: {exc}"
                            ),
                        )
                    )
                    return

                yield self._sse(
                    self._thinking_dict(
                        text=(
                            f"LLM 响应超时，正在基于当前节点上下文自动重试，"
                            f"第 {current_retry} 次尝试..."
                        ),
                        source="engine",
                        category="system",
                        importance="high",
                    )
                )
                has_checkpoint = await has_persisted_session(session_id)
                active_graph_input = {} if has_checkpoint else graph_input
                self._llm_reasoning_emitted = False

            except Exception as exc:
                tb = traceback.format_exc()
                err_str = str(exc)
                if (
                    "incomplete chunked read" in err_str
                    or "peer closed connection" in err_str
                ):
                    err_str = (
                        "与 LLM 服务的连接被意外中断（incomplete chunked read）。"
                        "请检查网络连接或 API 服务状态后重试。"
                    )
                elif "recursion limit" in err_str.lower() or "recursion_limit" in err_str:
                    err_str = (
                        "LangGraph 递归深度达到当前上限。为防止超出预期Token上限，任务被中断。"
                        "如果这是一个合法的复杂任务，请联系管理员将设置为更大的整数，"
    
                    )
                yield self._sse(
                    self._event_payload("error", error=err_str, traceback=tb)
                )
                return

    # ── Inner generator ────────────────────────────────────────────────────────

    async def _graph_query_loop(
        self,
        graph_input: Any,
        graph_config: dict,
    ) -> AsyncGenerator[dict, None]:
        """【内层生成器】封装 LangGraph 纯粹的图执行逻辑。

        每个 LangGraph ``astream_events`` 底层事件经过 ``_parse_langgraph_event``
        解析为标准化 dict 后 yield 给外层；循环结束后检查检查点快照并 yield
        ``interrupt`` 或 ``done`` 事件。
        """
        graph = get_compiled_graph()

        async for raw_event in graph.astream_events(
            graph_input,
            version="v2",
            config=graph_config,
        ):
            for parsed in self._parse_langgraph_event(raw_event):
                yield parsed

        # ── Post-loop: check for pending HITL interrupts ───────────────────────
        snapshot = await graph.aget_state(graph_config)
        if snapshot.interrupts:
            pending = snapshot.interrupts[0]
            pending_value = (
                pending.value if isinstance(pending.value, dict) else {}
            )
            if pending_value.get("type") == "approval_required":
                yield self._event_payload(
                    "approval_required",
                    tool_name=str(pending_value.get("tool_name", "")),
                    args=pending_value.get("args", {}),
                    tool_call_id=str(pending_value.get("tool_call_id", "")),
                    interrupt_id=pending.id,
                )
            elif pending_value.get("type") == "plan_approval_request":
                yield self._event_payload(
                    "plan_approval_request",
                    plan_id=str(pending_value.get("plan_id", "")),
                    plan_file_ref=str(pending_value.get("plan_file_ref", "")),
                    summary=str(pending_value.get("summary", "")),
                    status=str(pending_value.get("status", "pending_approval")),
                    mode=str(pending_value.get("mode", "plan")),
                    interrupt_id=pending.id,
                )
            else:
                yield self._event_payload(
                    "interrupt",
                    question=str(pending_value.get("question", "")),
                    options=list(pending_value.get("options", [])),
                    called_tools=list(pending_value.get("called_tools", [])),
                    known_smiles=pending_value.get("known_smiles"),
                    interrupt_id=pending.id,
                )
        else:
            checkpoint_id = (
                snapshot.config.get("configurable", {}).get("checkpoint_id")
            )
            yield self._event_payload("done", checkpoint_id=checkpoint_id)

    # ── Approval resume generator ──────────────────────────────────────────────

    async def resume_approval(
        self,
        *,
        action: str,
        args: dict | None,
        plan_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """【审批恢复生成器】处理前端的 approve / reject / modify 决策。

        向 LangGraph Checkpointer 发送 ``Command(resume=...)``，唤醒因 HEAVY_TOOLS
        审批而挂起的图，并将后续执行结果以 SSE 流的形式返回。
        不进行额外的 DB 写入——恢复操作复用 LangGraph 原生 Checkpointer 路径。
        """
        if plan_id and action == "modify":
            content = str((args or {}).get("content") or (args or {}).get("plan_content") or (args or {}).get("markdown") or "").strip()
            if not content:
                yield self._sse(self._event_payload("error", error="modify plan requires 'content' or 'plan_content'."))
                return
            try:
                pointer = update_plan_file(session_id=self.session_id, plan_id=plan_id, content=content)
            except Exception as exc:
                yield self._sse(self._event_payload("error", error=str(exc)))
                return

            yield self._sse(
                self._event_payload(
                    "plan_modified",
                    plan_id=pointer.plan_id,
                    plan_file_ref=pointer.plan_file_ref,
                    summary=pointer.summary,
                    status=pointer.status,
                )
            )
            yield self._sse(self._event_payload("done", checkpoint_id=None))
            return

        graph_config = {
            "configurable": {
                "thread_id": self.session_id,
                "session_id": self.session_id,
                "turn_id": self.turn_id,
            },
            "recursion_limit": _graph_recursion_limit(),
        }

        resume_action = action
        if plan_id and action == "approve":
            resume_action = "execute_plan"
        elif plan_id and action == "reject":
            resume_action = "reject_plan"

        resume_payload = Command(
            resume={"action": resume_action, "plan_id": plan_id, "args": args or {}}
        )

        yield self._sse(self._event_payload("run_started", message=f"[approval:{action}]"))

        try:
            async for event_dict in self._graph_query_loop(resume_payload, graph_config):
                if event_dict.get("type") == "tool_end":
                    event_dict = await self._intercept_and_collapse_artifact(event_dict)

                withheld = self._withheld_error_message(event_dict)
                if withheld is not None:
                    logger.warning("resume_approval 触发错误扣留: %s", withheld)
                    # For the approval resume path we surface the error directly
                    # rather than retrying (the user already made a decision).
                    yield self._sse(
                        self._event_payload("error", error=withheld)
                    )
                    return

                yield self._sse(event_dict)

        except Exception as exc:
            tb = traceback.format_exc()
            yield self._sse(self._event_payload("error", error=str(exc), traceback=tb))

    # ── LangGraph event parser ─────────────────────────────────────────────────

    def _parse_langgraph_event(self, event: dict[str, Any]) -> list[dict]:
        """将单个 LangGraph 底层事件转化为 0 或多个标准化 dict。

        不含任何 SSE 格式化；所有输出只是 Python dict。
        """
        results: list[dict] = []
        event_name: str = event["event"]
        node_name: str = event.get("metadata", {}).get("langgraph_node", "")

        # ── 1. LLM token streaming ─────────────────────────────────────────────
        # Accepts both root-agent nodes and sub-agent nodes (prefix "sub_agent").
        is_sub_agent_node = node_name.startswith(_SUB_AGENT_NODE_PREFIX)
        if event_name == "on_chat_model_stream" and (
            node_name in _STREAMING_NODES or is_sub_agent_node
        ):
            chunk = event["data"].get("chunk")
            if chunk is not None:
                self._debug_reasoning_payload("stream", node_name, chunk)
                raw = getattr(chunk, "content", "") or ""
                token, thinking_token = _extract_stream_text(raw, chunk)

                if thinking_token:
                    self._llm_reasoning_emitted = True
                    results.append(
                        self._thinking_dict(
                            text=thinking_token,
                            source="llm_reasoning",
                            done=False,
                            category="llm",
                            importance="high",
                            group_key="llm_reasoning",
                        )
                    )

                if token:
                    token_payload = self._event_payload(
                        "token", node=node_name, content=token
                    )
                    if is_sub_agent_node:
                        token_payload["source"] = "sub_agent"
                    results.append(token_payload)

        elif event_name == "on_chat_model_end" and (
            node_name in _STREAMING_NODES or is_sub_agent_node
        ):
            output_msg = event.get("data", {}).get("output")
            # Some providers aggregate reasoning only at model-end; emit it only
            # when the streaming phase produced no reasoning, to avoid duplicates.
            if output_msg is not None and not self._llm_reasoning_emitted:
                self._debug_reasoning_payload("end", node_name, output_msg)
                raw = getattr(output_msg, "content", "") or ""
                _, thinking_token = _extract_stream_text(raw, output_msg)
                if thinking_token:
                    self._llm_reasoning_emitted = True
                    results.append(
                        self._thinking_dict(
                            text=thinking_token,
                            source="llm_reasoning",
                            done=True,
                            category="llm",
                            importance="high",
                            group_key="llm_reasoning",
                        )
                    )

            usage_metadata = getattr(output_msg, "usage_metadata", None) or {}
            if isinstance(usage_metadata, dict) and usage_metadata:
                input_tokens = int(usage_metadata.get("input_tokens") or 0)
                output_tokens = int(
                    usage_metadata.get("output_tokens")
                    or usage_metadata.get("completion_tokens")
                    or 0
                )
                total_tokens = int(
                    usage_metadata.get("total_tokens")
                    or (input_tokens + output_tokens)
                )
                response_metadata = getattr(output_msg, "response_metadata", None) or {}
                model_name = None
                if isinstance(response_metadata, dict):
                    model_name = response_metadata.get("model_name") or response_metadata.get("model")

                if input_tokens or output_tokens or total_tokens:
                    results.append(
                        self._usage_dict(
                            node=node_name,
                            model=str(model_name) if model_name else None,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens,
                        )
                    )

        # ── 2. Node lifecycle events ───────────────────────────────────────────
        elif (
            event_name == "on_chain_start"
            and node_name in _LIFECYCLE_NODES
            and event.get("name") == node_name
        ):
            results.append(self._event_payload("node_start", node=node_name))
            thinking_text = _NODE_REASONING_MESSAGES.get((node_name, event_name))
            if thinking_text:
                results.append(
                    self._thinking_dict(
                        text=thinking_text,
                        source=node_name,
                        category="node",
                        importance="low",
                        group_key=node_name,
                    )
                )

        elif (
            event_name == "on_chain_end"
            and node_name in _LIFECYCLE_NODES
            and event.get("name") == node_name
        ):
            results.append(self._event_payload("node_end", node=node_name))
            thinking_text = _NODE_REASONING_MESSAGES.get((node_name, event_name))
            if thinking_text:
                results.append(
                    self._thinking_dict(
                        text=thinking_text,
                        source=node_name,
                        category="node",
                        importance="low",
                        group_key=node_name,
                    )
                )

        # ── 3. Tool lifecycle events ───────────────────────────────────────────
        elif event_name == "on_tool_start":
            tool_name = event["name"]
            if tool_name not in _SILENT_TOOL_NAMES:
                tool_input = event["data"].get("input", {})
                results.append(
                    self._event_payload("tool_start", tool=tool_name, input=tool_input)
                )
                results.append(
                    self._thinking_dict(
                        text=self._tool_reasoning_text(tool_name, "start", tool_input),
                        source="tools_executor",
                        category="tool",
                        importance="high",
                        group_key=tool_name,
                    )
                )

        elif event_name == "on_tool_end":
            tool_name = event["name"]
            if tool_name not in _SILENT_TOOL_NAMES:
                raw_output = event["data"].get("output")
                parsed_output = _sanitize_tool_output(
                    tool_name, _parse_tool_output(raw_output)
                )
                results.append(
                    self._event_payload(
                        "tool_end", tool=tool_name, output=parsed_output
                    )
                )
                if isinstance(parsed_output, dict) and parsed_output.get("error"):
                    results.append(
                        self._thinking_dict(
                            text=self._tool_reasoning_text(
                                tool_name, "end", parsed_output
                            ),
                            source="tools_executor",
                            category="error",
                            importance="high",
                            group_key=tool_name,
                        )
                    )

        # ── 4. Custom events dispatched from worker nodes ──────────────────────
        elif event_name == "on_custom_event":
            custom_name: str = event.get("name", "")
            custom_data: dict = event.get("data", {})
            parsed = self._handle_custom_event(custom_name, custom_data)
            if parsed is not None:
                results.append(parsed)

        return results

    # ── Interceptors ──────────────────────────────────────────────────────────

    async def _intercept_and_collapse_artifact(self, event_dict: dict) -> dict:
        """【控制面/数据面隔离】剥离庞大工件，只向前端传递轻量级 ID 指针。

        被剥离的原始内容写入 Redis（经 ``artifact_store``），可通过
        ``GET /api/v1/chat/artifacts/{artifact_id}`` 按需检索，而不会撑爆
        LLM 上下文或 SSE 帧。Redis 不可用时自动降级到进程内字典。
        """
        output = event_dict.get("output", {})
        if not isinstance(output, dict):
            return event_dict

        output = dict(output)
        for key in list(output.keys()):
            if key in _ARTIFACT_COLLAPSE_KEYS:
                artifact_id = f"art_{uuid4().hex[:8]}"
                raw_value = output.pop(key)
                await store_engine_artifact(artifact_id, raw_value)
                output[f"{key}_artifact_id"] = artifact_id
                output["system_notice"] = (
                    f"文件已生成并挂载为 {artifact_id}，无需读取原始内容。"
                )
                logger.info(
                    "Collapsed artifact key '%s' → %s (session=%s)",
                    key,
                    artifact_id,
                    self.session_id,
                )

        event_dict = dict(event_dict)
        event_dict["output"] = output
        return event_dict

    def _withheld_error_message(self, event_dict: dict) -> str | None:
        """【错误扣留】识别可自愈化学错误，返回错误消息；否则返回 None。

        目前识别的可扣留错误类型：
        - RDKit 价键非法 (valence)
        - SMILES 解析失败 (invalid smiles)
        - Kekulize 失败
        - 分子 sanitize 失败
        """
        if event_dict.get("type") != "tool_end":
            return None
        output = event_dict.get("output", {})
        if not isinstance(output, dict) or "error" not in output:
            return None
        err_msg = str(output["error"]).lower()
        if any(kw in err_msg for kw in _WITHHELD_ERROR_KEYWORDS):
            return str(output["error"])
        return None

    # ── Custom event routing ───────────────────────────────────────────────────

    def _handle_custom_event(self, name: str, data: dict) -> dict | None:
        """将 LangGraph 自定义事件（``on_custom_event``）转换为标准化 dict。"""
        if name == "artifact":
            return self._event_payload("artifact", **data)
        if name == "thinking":
            return self._thinking_dict(
                text=data.get("text", ""),
                iteration=data.get("iteration", 0),
                done=data.get("done", True),
                source=data.get("source", "chem_agent"),
                category=data.get("category"),
                importance=data.get("importance", "high"),
                group_key=data.get("group_key"),
            )
        if name == "task_update":
            return self._event_payload(
                "task_update",
                tasks=data.get("tasks", []),
                source=data.get("source", "tools_executor"),
            )
        if name == "shadow_lab_error":
            return self._event_payload(
                "shadow_error",
                smiles=data.get("smiles"),
                error=data.get("error"),
            )
        return None

    # ── Debug helpers ──────────────────────────────────────────────────────────

    def _debug_reasoning_payload(
        self, stage: str, node_name: str, message_obj: object
    ) -> None:
        if not _env_truthy("DEBUG_REASONING_RAW", False):
            return
        raw_content = getattr(message_obj, "content", None)
        additional_kwargs = getattr(message_obj, "additional_kwargs", None)
        log_line = (
            "[reasoning-debug] "
            f"stage={stage} node={node_name} "
            f"content_type={type(raw_content).__name__ if raw_content is not None else 'None'} "
            f"additional_keys="
            f"{list(additional_kwargs.keys()) if isinstance(additional_kwargs, dict) else None} "
            f"content_preview={_preview(raw_content)} "
            f"additional_preview={_preview(additional_kwargs)}"
        )
        logger.debug(log_line)

    @staticmethod
    def _tool_reasoning_text(
        tool_name: str,
        stage: str,
        payload: dict | str | None = None,
    ) -> str:
        pretty_name = tool_name.replace("tool_", "")
        label = _TOOL_LABELS.get(pretty_name, pretty_name)
        if stage == "start":
            return f"正在调用：{label}"
        if stage == "end":
            if isinstance(payload, dict) and "error" in payload:
                return f"{label}失败：{payload['error']}"
            return f"{label}已完成"
        return f"工具完成：{label}。"

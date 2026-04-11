"""
Message sanitization for LangGraph state and LLM API calls.

Provides two sanitization layers:
- ``sanitize_messages_for_state()``: Thin passthrough — strips binary fields from
  ToolMessage content before writing to checkpointer.  Context Firewall (char-limit
  enforcement) has been removed; use ``normalize_messages_for_api()`` for
  LLM-call-time compression instead.
- ``normalize_messages_for_api()``: Pre-LLM-call normalization with 4-level
  compression: (1) drop virtual SystemMessages, (2) close orphan tool_calls,
  (3) snip/truncate historical ToolMessages, (4) merge consecutive same-type
  messages.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any, Awaitable, Callable, cast

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

_STRIP_LLM_FIELDS = frozenset({
    "image", "structure_image", "highlighted_image",
    "molecule_image", "scaffold_image",
    "sdf_content", "pdbqt_content", "zip_bytes", "atoms",
})
ToolResult = dict[str, Any]
ToolPostprocessor = Callable[[ToolResult, dict[str, Any], list[dict], RunnableConfig], Awaitable[ToolResult]]
_OMITTED_TOOL_RESULT = "[System] Tool result omitted (history limit)."
_OMITTED_TOOL_RESULT_COMPACT = "[Omitted]"





async def sanitize_message_for_state(message: BaseMessage, *, source: str) -> BaseMessage:  # noqa: ARG001
    """No-op passthrough. Context Firewall (char-limit enforcement) has been removed.
    LLM-call-time compression is handled by normalize_messages_for_api().
    """
    return message


async def sanitize_messages_for_state(
    messages: Sequence[BaseMessage],
    *,
    source: str,
) -> list[BaseMessage]:
    """No-op passthrough — callers preserved for backward-compatibility."""
    return list(messages)



# ── strip_binary_fields (also used by postprocessors) ─────────────────────────

def _strip_binary_fields_recursive(data: Any, *, path: str = "") -> tuple[Any, list[str]]:
    removed_paths: list[str] = []

    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            next_path = f"{path}.{key}" if path else str(key)
            if key in _STRIP_LLM_FIELDS:
                removed_paths.append(next_path)
                continue
            cleaned_value, nested_removed = _strip_binary_fields_recursive(value, path=next_path)
            cleaned[key] = cleaned_value
            removed_paths.extend(nested_removed)
        return cleaned, removed_paths

    if isinstance(data, list):
        cleaned_list: list[Any] = []
        for index, value in enumerate(data):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            cleaned_value, nested_removed = _strip_binary_fields_recursive(value, path=next_path)
            cleaned_list.append(cleaned_value)
            removed_paths.extend(nested_removed)
        return cleaned_list, removed_paths

    if isinstance(data, tuple):
        cleaned_items: list[Any] = []
        for index, value in enumerate(data):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            cleaned_value, nested_removed = _strip_binary_fields_recursive(value, path=next_path)
            cleaned_items.append(cleaned_value)
            removed_paths.extend(nested_removed)
        return tuple(cleaned_items), removed_paths

    return data, removed_paths


def strip_binary_fields(data: dict) -> dict:
    cleaned, _ = _strip_binary_fields_recursive(data)
    return cast(dict[str, Any], cleaned)


def strip_binary_fields_with_report(data: dict) -> tuple[dict[str, Any], list[str]]:
    cleaned, removed_paths = _strip_binary_fields_recursive(data)
    return cast(dict[str, Any], cleaned), removed_paths

def normalize_messages_for_api(
    messages: Sequence[BaseMessage],
    max_tool_history: int = 15,
    max_tool_length: int = 15000,
) -> list[BaseMessage]:
    """JIT in-memory sanitizer: produce a legally-sequenced message list for the
    LLM API without triggering any DB writes.

    Handles four failure modes:
    1. Virtual SystemMessages injected by the frontend.
    2. Orphan ToolMessages whose AI request was never recorded.
    3. Dangling tool_calls whose ToolMessage was lost due to user interruption —
       closure messages are injected *immediately after* the AIMessage, not
       appended at the end, so the API sequence is never broken.
    4. Consecutive same-type messages that some models reject.
    """
    if not messages:
        return []

    # 1. Drop virtual frontend SystemMessages.
    filtered = [
        m for m in messages
        if not (isinstance(m, SystemMessage) and m.additional_kwargs.get("is_virtual"))
    ]

    final_messages: list[BaseMessage] = []
    pending_tool_calls: dict[str, Any] = {}

    def _flush_pending() -> None:
        """Insert closure ToolMessages for any dangling tool_calls in-place,
        immediately before the next non-ToolMessage.  This keeps the sequence
        legal: ToolMessages must follow their AIMessage without interruption."""
        for tool_id, tc in pending_tool_calls.items():
            final_messages.append(
                ToolMessage(
                    content="[System] Tool execution interrupted by user.",
                    tool_call_id=tool_id,
                    name=tc["name"],
                )
            )
        pending_tool_calls.clear()

    # 2+3. Tool-call pairing validation with inline dangling-call closure.
    #      When a non-ToolMessage is encountered while tool_calls are still
    #      pending, close them *before* appending that message so that the
    #      API sequence is always AIMessage → ToolMessage(s) → next message.
    for msg in filtered:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            # Close any dangling calls from a previous AI turn first.
            _flush_pending()
            for tc in msg.tool_calls:
                tool_call_id = str(tc.get("id") or "").strip()
                if tool_call_id:
                    pending_tool_calls[tool_call_id] = tc
            final_messages.append(msg)
        elif isinstance(msg, ToolMessage):
            if msg.tool_call_id in pending_tool_calls:
                del pending_tool_calls[msg.tool_call_id]
                final_messages.append(msg)
            # Drop orphan ToolMessages that have no matching AIMessage.
        else:
            # Any non-tool message breaks the tool-call window — close first.
            _flush_pending()
            final_messages.append(msg)

    # Close any tool_calls still pending at the very end of the sequence.
    _flush_pending()

    # 4. Compress ToolMessage history (reverse-iterate, newest-first).
    #    4a. Snip: replace old ToolMessages beyond max_tool_history with a placeholder.
    #    4b. Budget: head+tail truncate results that exceed max_tool_length.
    tool_count = 0
    compressed: list[BaseMessage] = []
    for msg in reversed(final_messages):
        if isinstance(msg, ToolMessage):
            tool_count += 1
            if tool_count > max_tool_history:
                # 4a — too far back in history; replace with a tiny sentinel
                compressed.append(
                    ToolMessage(
                        content=_OMITTED_TOOL_RESULT,
                        tool_call_id=msg.tool_call_id,
                        name=msg.name,
                    )
                )
            elif isinstance(msg.content, str) and len(msg.content) > max_tool_length:
                # 4b — result is too large; keep head and tail
                half = max_tool_length // 2
                head = msg.content[:half]
                tail = msg.content[-half:]
                omitted = len(msg.content) - max_tool_length
                truncated = f"{head}\n…[{omitted} chars omitted]…\n{tail}"
                compressed.append(
                    ToolMessage(
                        content=truncated,
                        tool_call_id=msg.tool_call_id,
                        name=msg.name,
                    )
                )
            else:
                compressed.append(msg)
        else:
            compressed.append(msg)
    compressed.reverse()

    # 4c. Collapse omitted ToolMessages across the whole older-history region
    #     into one informative sentinel plus ultra-short fillers. We keep one
    #     ToolMessage per tool_call_id so the API sequence remains legal.
    omitted_messages = [
        msg
        for msg in compressed
        if isinstance(msg, ToolMessage) and msg.content == _OMITTED_TOOL_RESULT
    ]
    omitted_count = len(omitted_messages)
    aggregated: list[BaseMessage] = []
    first_omitted_emitted = False

    for msg in compressed:
        if isinstance(msg, ToolMessage) and msg.content == _OMITTED_TOOL_RESULT:
            summary_content = _OMITTED_TOOL_RESULT
            if omitted_count > 1:
                if not first_omitted_emitted:
                    summary_content = (
                        f"[System] {omitted_count} earlier tool results omitted (history limit); "
                        "rely on task summaries and molecule workspace."
                    )
                    first_omitted_emitted = True
                else:
                    summary_content = _OMITTED_TOOL_RESULT_COMPACT

            aggregated.append(
                ToolMessage(
                    content=summary_content,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                )
            )
            continue

        aggregated.append(msg)

    # 5. Merge consecutive same-type messages.
    #    Exempt from merging:
    #    - ToolMessages: each has a unique tool_call_id; merging destroys all but the first.
    #    - AIMessages carrying tool_calls: merging destroys the tool-call structure.
    merged: list[BaseMessage] = []
    for msg in aggregated:
        if (
            merged
            and type(msg) is type(merged[-1])
            and not isinstance(msg, ToolMessage)
            and not (isinstance(msg, AIMessage) and msg.tool_calls)
            and not (isinstance(merged[-1], AIMessage) and merged[-1].tool_calls)
        ):
            merged[-1].content += f"\n\n{msg.content}"
        else:
            merged.append(msg)

    return merged



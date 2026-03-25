"""
Reasoning-aware OpenAI model client for AG2 V1 pipeline.

The stable ``OpenAIClient.create()`` streaming loop only extracts
``delta.content`` and ``delta.tool_calls`` — it silently drops
``delta.reasoning_content`` emitted by reasoning models (o1, o3, o4-mini,
deepseek-r1, etc.).

This module provides a drop-in V1 ``ModelClient`` that:
1. Calls OpenAI via the official SDK (same as ``OpenAIClient``)
2. Captures ``reasoning_content`` from streaming deltas and emits them
   as ``ReasoningChunkEvent`` via ``IOStream``
3. Emits ``StreamEvent`` for normal content (parity with vanilla client)
4. Assembles a ``ChatCompletion``-compatible response for downstream AG2

Registration
------------
Use ``brain.register_model_client(cls=ReasoningAwareClient)`` after agent
creation.  The ``build_llm_config()`` must include
``"model_client_cls": "ReasoningAwareClient"`` so ``OpenAIWrapper`` creates
the placeholder that gets replaced.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Sequence

from openai import OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.completion_usage import CompletionUsage

from autogen.events.client_events import StreamEvent
from autogen.io.base import IOStream

logger = logging.getLogger(__name__)


# ── Custom event for reasoning tokens ─────────────────────────────────────────


@dataclass
class ReasoningChunkEvent:
    """Emitted for each reasoning token chunk during streaming.

    NOT an AG2 event class — it's our own lightweight event that we emit
    through ``IOStream.send()`` and intercept in ``_event_to_frames()``.
    """

    content: str


# ── Response wrapper matching ModelClientResponseProtocol ─────────────────────


class _ReasoningResponse:
    """Minimal wrapper satisfying AG2's ``ModelClientResponseProtocol``."""

    def __init__(self, completion: ChatCompletion) -> None:
        self._completion = completion

    @property
    def choices(self) -> Sequence[Choice]:
        return self._completion.choices

    @property
    def model(self) -> str:
        return self._completion.model

    @property
    def usage(self) -> CompletionUsage | None:
        return self._completion.usage

    @property
    def raw(self) -> ChatCompletion:
        return self._completion


# ── V1 ModelClient implementation ─────────────────────────────────────────────


class ReasoningAwareClient:
    """AG2 V1 ModelClient that captures ``reasoning_content`` from streaming.

    Constructor signature: ``__init__(config: dict, **kwargs)`` — called by
    ``OpenAIWrapper.register_model_client()``.
    """

    def __init__(self, config: dict[str, Any], **kwargs: Any) -> None:
        self._model = config.get("model", "gpt-4o-mini")
        api_key = config.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
        base_url = config.get("base_url") or os.environ.get("OPENAI_BASE_URL")

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client = OpenAI(**client_kwargs)
        logger.info(
            "ReasoningAwareClient initialised: model=%s, base_url=%s",
            self._model,
            base_url or "(default)",
        )

    # ── Core create() — sync, called from ``a_generate_oai_reply`` thread ──

    def create(self, params: dict[str, Any]) -> _ReasoningResponse:
        """Call OpenAI, capture reasoning_content, emit events, return response."""
        messages = params.get("messages", [])
        model = params.get("model", self._model)

        # Build API kwargs, forwarding tool definitions if present
        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        # Forward tools / tool_choice
        if params.get("tools"):
            api_kwargs["tools"] = params["tools"]
        if params.get("tool_choice"):
            api_kwargs["tool_choice"] = params["tool_choice"]

        # Forward temperature / max_tokens if set
        for key in ("temperature", "max_tokens", "top_p", "reasoning_effort"):
            if key in params and params[key] is not None:
                api_kwargs[key] = params[key]

        iostream = IOStream.get_default()

        # Accumulators
        full_content = ""
        full_reasoning = ""
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage: CompletionUsage | None = None
        completion_id = ""

        stream = self._client.chat.completions.create(**api_kwargs)

        for chunk in stream:
            completion_id = completion_id or chunk.id or ""

            if not chunk.choices:
                # Final chunk with usage only
                if chunk.usage:
                    usage = chunk.usage
                continue

            delta = chunk.choices[0].delta
            choice_finish = chunk.choices[0].finish_reason

            if choice_finish:
                finish_reason = choice_finish

            # ── Reasoning content ─────────────────────────────────────────
            reasoning = getattr(delta, "reasoning_content", None) or getattr(
                delta, "reasoning", None
            )
            if reasoning:
                full_reasoning += reasoning
                iostream.send(ReasoningChunkEvent(content=reasoning))

            # ── Normal content ────────────────────────────────────────────
            content = delta.content
            if content is not None:
                full_content += content
                iostream.send(StreamEvent(content=content))

            # ── Tool calls (accumulated by index) ─────────────────────────
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {
                            "id": tc.id or "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = tool_calls_by_index[idx]
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            entry["function"]["name"] = tc.function.name
                        if tc.function.arguments:
                            entry["function"]["arguments"] += tc.function.arguments

        # ── Assemble ChatCompletion ───────────────────────────────────────
        assembled_tool_calls = None
        if tool_calls_by_index:
            from openai.types.chat.chat_completion_message_tool_call import (
                ChatCompletionMessageToolCall,
                Function,
            )

            assembled_tool_calls = [
                ChatCompletionMessageToolCall(
                    id=tc["id"],
                    type="function",
                    function=Function(
                        name=tc["function"]["name"],
                        arguments=tc["function"]["arguments"],
                    ),
                )
                for tc in sorted(tool_calls_by_index.values(), key=lambda x: x["id"])
            ]

        message = ChatCompletionMessage(
            role="assistant",
            content=full_content or None,
            tool_calls=assembled_tool_calls,
        )

        completion = ChatCompletion(
            id=completion_id or f"chatcmpl-reasoning-{int(time.time())}",
            choices=[
                Choice(
                    index=0,
                    message=message,
                    finish_reason=finish_reason or "stop",
                )
            ],
            created=int(time.time()),
            model=model,
            object="chat.completion",
            usage=usage,
        )

        return _ReasoningResponse(completion)

    # ── Required V1 ModelClient methods ───────────────────────────────────

    def message_retrieval(self, response: _ReasoningResponse) -> list[str]:
        """Extract text content from the response for AG2's message history."""
        choices = response.choices
        if not choices:
            return []

        msg = choices[0].message
        # If the model used tool calls, return the raw ChatCompletionMessage
        # so AG2's tool-call processing pipeline can handle it.
        if msg.tool_calls:
            return [msg]  # type: ignore[list-item]
        return [msg.content or ""]

    def cost(self, response: _ReasoningResponse) -> float:
        """Estimate cost — returns 0; real billing is handled externally."""
        return 0.0

    @staticmethod
    def get_usage(response: _ReasoningResponse) -> dict[str, Any]:
        """Return token usage dict for AG2's tracking."""
        usage = response.usage
        if not usage:
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
                "model": response.model,
            }
        return {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "cost": 0.0,
            "model": response.model,
        }

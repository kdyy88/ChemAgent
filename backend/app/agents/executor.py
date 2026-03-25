"""
Executor — the tool-running sentinel in ChemAgent's Caller/Executor architecture.

The executor has **no LLM** (``llm_config=False``).  Its only jobs are:
1. Execute tool functions when ChemBrain issues a tool call.
2. Detect termination sentinels (``[AWAITING_APPROVAL]`` or ``[TERMINATE]``)
   in ChemBrain's output and halt the conversation accordingly.

The caller/executor separation ensures that reasoning (LLM) and execution
(deterministic Python) stay cleanly isolated.
"""

from __future__ import annotations

from autogen import ConversableAgent


_SENTINELS = ("[AWAITING_APPROVAL]", "[TERMINATE]")


def _is_termination_msg(msg: dict) -> bool:
    """Return True if the message contains any sentinel keyword."""
    content = msg.get("content") or ""
    return any(sentinel in content for sentinel in _SENTINELS)


def create_executor() -> ConversableAgent:
    """Create the executor agent (no LLM, executes tools, detects sentinels)."""
    return ConversableAgent(
        name="executor",
        llm_config=False,
        human_input_mode="NEVER",
        is_termination_msg=_is_termination_msg,
        max_consecutive_auto_reply=30,
        description=(
            "Silent executor that runs tool functions and detects "
            "termination sentinels — no LLM reasoning."
        ),
    )

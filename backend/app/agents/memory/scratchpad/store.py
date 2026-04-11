"""
agents/memory/scratchpad — routed scratchpad (side-channel memo store).

Placeholder for resolving long-context Token explosion in multi-step
agentic loops.  Future implementation will store intermediate reasoning
and large tool outputs out-of-band (Redis or local file), injecting only
a compact summary back into the LangGraph message thread.
"""
from __future__ import annotations

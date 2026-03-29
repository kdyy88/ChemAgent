"""
ChemTeamRouter — deterministic hub-and-spoke speaker selection.

This callable replaces GroupChat's LLM-based "auto" speaker selection with a
pure Python state machine, making routing:
  • Deterministic — no LLM coin-toss on who speaks next.
  • Typed         — routing target read from ContextVariables, NOT parsed from
                    LLM text output.  Eliminates the last regex dependency.
  • Cheap         — zero extra LLM calls for routing decisions.
  • Debuggable    — routing logic is plain Python, not buried in a prompt.

ContextVariables integration
─────────────────────────────
The Planner now calls ``set_routing_target(target)`` (a registered tool) to
write the next destination into ``ctx["next_agent"]``.  The router consumes
this value and clears it — the LLM never needs to emit ``[ROUTE: xxx]`` text.

Routing table
─────────────
  any message with ``tool_calls``           → tool_executor
  tool_executor just spoke                  → reviewer
  reviewer said [OK]  (text still used)     → planner  (planner reads ctx next)
  reviewer said [RETRY: x]                  → specialist x  (bypass planner)
  planner called set_routing_target("x")    → specialist x  (ctx["next_agent"])
  planner called mark_all_steps_complete()  → planner itself (to emit final answer + [TERMINATE])
  planner said [TERMINATE] / [AWAITING]     → (GroupChatManager terminates the loop)
  specialist said [DONE]                    → reviewer
  initial / unknown                         → planner
"""

from __future__ import annotations

import re

from autogen import ConversableAgent
from autogen import GroupChat
from autogen.agentchat.contrib.swarm_agent import ContextVariables

# Reviewer verdict pattern — still text-based, but Reviewer is intentionally
# kept as a simple yes/no gatekeeper so this single regex is acceptable.
_RETRY_RE = re.compile(r"\[RETRY:\s*(data_specialist|computation_specialist)\]")


class ChemTeamRouter:
    """Hub-and-spoke router backed by ContextVariables for typed routing.

    Pass an instance as ``speaker_selection_method`` to ``GroupChat``.
    ``func_call_filter`` must be set to ``False`` — this router handles tool
    dispatch itself via the ``tool_calls`` check.
    """

    def __init__(
        self,
        agents: dict[str, ConversableAgent],
        ctx: ContextVariables,
    ) -> None:
        """
        Args:
            agents: mapping of stable agent names → ConversableAgent instances.
                    Expected keys: planner, data_specialist, computation_specialist,
                    reviewer, tool_executor.
            ctx: shared ContextVariables for this session.  The router reads
                 ``ctx["next_agent"]`` to make typed routing decisions instead
                 of parsing ``[ROUTE: xxx]`` from LLM text output.
        """
        self.agents = agents
        self.ctx = ctx

    # ── AG2 speaker_selection_method interface ────────────────────────────────

    def __call__(
        self, last_speaker: ConversableAgent, groupchat: GroupChat
    ) -> ConversableAgent:
        """Return the next agent to speak.

        Routing priority order:
          1. tool_calls in last message  → tool_executor  (handles ALL agents' tool calls)
          2. last_speaker == tool_executor → reviewer
          3. last_speaker == reviewer     → check [RETRY: x] text / default planner
          4. last_speaker == planner      → read ctx["next_agent"] (typed, no regex)
          5. last_speaker == specialist   → reviewer ([DONE] or after tool run)
          6. default                      → planner
        """
        messages = groupchat.messages
        last_msg = messages[-1] if messages else {}
        content = (last_msg.get("content") or "").strip()
        name = last_speaker.name

        # ── 1. Tool call pending → tool_executor ──────────────────────────────
        if last_msg.get("tool_calls"):
            return self.agents["tool_executor"]

        # ── 2. After tool_executor → reviewer ────────────────────────────────
        if name == "tool_executor":
            return self.agents["reviewer"]

        # ── 3. After reviewer ─────────────────────────────────────────────────
        if name == "reviewer":
            retry_match = _RETRY_RE.search(content)
            if retry_match:
                target = retry_match.group(1)
                if target in self.agents:
                    return self.agents[target]
            # [OK] or unexpected → planner picks up (reads ctx for next step)
            return self.agents["planner"]

        # ── 4. After planner — typed ctx read ────────────────────────────────
        if name == "planner":
            next_agent = self.ctx.get("next_agent", "")
            if next_agent and next_agent in self.agents:
                # Consume the routing signal — prevents stale re-routing
                self.ctx["next_agent"] = ""
                return self.agents[next_agent]
            # No routing target set → planner is synthesising final answer or
            # GroupChatManager will terminate on [TERMINATE] / [AWAITING_APPROVAL]
            return self.agents["reviewer"]

        # ── 5. After data/computation specialist ──────────────────────────────
        if name in ("data_specialist", "computation_specialist"):
            return self.agents["reviewer"]

        # ── 6. Default: initial message or unknown ────────────────────────────
        return self.agents["planner"]

"""
ChemAgent shared session context — AG2 ContextVariables integration.

The Planner (coordinator agent) writes routing decisions into a
``ContextVariables`` instance via tool calls instead of emitting text
strings like ``[ROUTE: xxx]``.  ``set_routing_target`` returns a
``ReplyResult(target=AgentTarget(specialist))`` that DefaultPattern's
``GroupToolExecutor`` resolves into a deterministic speaker transition —
no regex, no text parsing.

Previously the old ``ChemTeamRouter`` read ``ctx["next_agent"]`` and
selected the next GroupChat speaker.  With ``DefaultPattern`` the routing
information lives in the ``ReplyResult.target`` field returned directly
from the tool call.  ``ctx["next_agent"]`` is still updated for
observability / debugging but is no longer the routing mechanism.

ContextVariables schema
───────────────────────
  state            : str  — "idle" | "awaiting_approval" | "executing" | "completed"
  current_plan     : str  — stored by ``submit_plan_for_approval``
  final_summary    : str  — stored by ``finish_workflow``
  next_agent       : str  — last routing target (observability only)

Control tools registered on **planner**
────────────────────────────────────────
  ``set_routing_target(target)``
      Returns ``ReplyResult(target=AgentTarget(specialist))`` — typed speaker
      selection replacing the fragile ``[ROUTE: xxx]`` text approach.

  ``submit_plan_for_approval`` / ``finish_workflow``
      Defined in ``control_tools.py`` — handle HITL and termination.
      ``mark_all_steps_complete`` is removed; ``finish_workflow`` subsumes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from autogen.agentchat.group import AgentTarget, ContextVariables, ReplyResult

if TYPE_CHECKING:
    from autogen import ConversableAgent

# Stable set of valid routing targets (used for ValueError guard)
_VALID_TARGETS = frozenset({"data_specialist", "computation_specialist"})


def make_session_context() -> ContextVariables:
    """Create a fresh ``ContextVariables`` for a new ChemAgent session.

    ``state`` tracks the conversation phase:
      - ``"idle"``               — waiting for user input
      - ``"awaiting_approval"``  — plan proposed; waiting for user approval
      - ``"executing"``          — Phase 2 in progress
      - ``"completed"``          — finish_workflow was called; summary ready
    """
    return ContextVariables(
        data={
            "state": "idle",
            "current_plan": "",    # set by submit_plan_for_approval
            "final_summary": "",   # set by finish_workflow
            "next_agent": "",      # set by set_routing_target (for observability)
        }
    )


def make_routing_tools(
    ctx: ContextVariables,
    agents_map: dict[str, "ConversableAgent"],
):
    """Return the ``set_routing_target`` closure bound to *ctx* and *agents_map*.

    The returned function is registered on the planner via
    ``register_function(fn, caller=planner, executor=planner)``.
    DefaultPattern's ``GroupToolExecutor`` picks it up from
    ``planner.tools`` and executes it when the planner calls it.

    Args:
        ctx:        the shared session ContextVariables
        agents_map: dict mapping agent name → ConversableAgent, used to
                    build the AgentTarget for the ReplyResult

    Returns:
        set_routing_target — closure that returns a typed ReplyResult
    """

    def set_routing_target(
        target: Annotated[
            str,
            "下一步要执行任务的专家 Agent 名称。必须是 'data_specialist' 或 "
            "'computation_specialist' 之一。",
        ],
    ) -> ReplyResult:
        """将控制权移交给指定专家，替代脆弱的 [ROUTE: xxx] 文本信号。

        返回 ``ReplyResult(target=AgentTarget(specialist))``，
        DefaultPattern 的 GroupToolExecutor 将据此把下一条消息路由给目标专家。
        无需在文本中输出任何标记符号。

        Args:
            target: 目标专家名称，'data_specialist' 或 'computation_specialist'
        """
        if target not in _VALID_TARGETS:
            raise ValueError(
                f"无效的路由目标 '{target}'。"
                f"必须是以下之一：{sorted(_VALID_TARGETS)}"
            )
        agent = agents_map[target]
        # Update ctx for observability / debugging (not used for actual routing)
        ctx["next_agent"] = target
        return ReplyResult(
            message=f"[路由] 将控制权移交给 {target}",
            context_variables=ctx,
            target=AgentTarget(agent),
        )

    return set_routing_target

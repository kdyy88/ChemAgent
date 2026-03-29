"""
ChemAgent workflow control tools — closure-based HITL and termination.

These tools replace fragile sentinel strings with deterministic Function
Calling.  They follow the **same closure pattern** as ``set_routing_target``
in ``context.py``: ``ctx`` is captured by closure so the function signature
only contains LLM-visible parameters — no ``ContextVariables`` parameter is
exposed.  This avoids the Pydantic ``TypeAdapter[ForwardRef('ContextVariables')]``
error that occurs when ``register_for_llm`` / ``get_function_schema`` tries
to build a JSON schema for the raw ``@tool`` function.

Factory functions
─────────────────
  ``make_submit_plan_for_approval(ctx)``
      Returns a ``submit_plan_for_approval(plan_details: str) -> ReplyResult``
      closure.  Registered via ``register_function(fn, caller=planner,
      executor=planner)`` in ``manager.py``.

  ``make_finish_workflow(ctx)``
      Returns a ``finish_workflow(final_summary: str) -> ReplyResult`` closure.
      Registered the same way.

How it works
────────────
1. Planner calls ``submit_plan_for_approval(plan_details="...")`` (Phase 1).
2. DefaultPattern's ``GroupToolExecutor`` executes the closure, which:
   a. Writes plan + state into the captured ``ctx`` (ContextVariables).
   b. Returns ``ReplyResult(target=TerminateTarget())``.
3. ``GroupToolExecutor`` resolves ``TerminateTarget`` → GroupChat stops.
4. ``events.py`` detects ``ExecutedFunctionEvent.func_name ==
   'submit_plan_for_approval'`` → sets ``session.state = 'awaiting_approval'``.
5. ``RunCompletionEvent`` guard suppresses ``run.finished`` during Phase 1.

Phase 2 (``finish_workflow``) follows the same path but sets
``ctx['state'] = 'completed'`` → ``run.finished`` IS emitted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autogen.agentchat.group import ReplyResult, TerminateTarget

if TYPE_CHECKING:
    from autogen.agentchat.group import ContextVariables


def make_submit_plan_for_approval(ctx: "ContextVariables"):
    """Return a ``submit_plan_for_approval`` closure bound to *ctx*.

    The returned function has only LLM-visible parameters (no ContextVariables
    in its signature) so ``register_function`` / ``get_function_schema`` can
    build a clean JSON schema without hitting Pydantic TypeAdapter issues.

    Args:
        ctx: The shared session ContextVariables for this team instance.
    """

    def submit_plan_for_approval(plan_details: str) -> ReplyResult:
        """【仅在规划阶段使用】完成任务拆解后，调用此工具将 <plan> 内容提交给用户审批。

        将计划的纯文本内容（无 XML 标签）传入 plan_details 参数。
        调用后对话暂停，等待用户批准——在用户批准前禁止继续执行任何步骤。

        Args:
            plan_details: 规划阶段产出的完整计划文本（供系统持久化和前端显示）。
        """
        ctx["current_plan"] = plan_details
        ctx["state"] = "awaiting_approval"
        return ReplyResult(
            message=f"计划已提交审批，等待用户确认：\n{plan_details}",
            context_variables=ctx,
            target=TerminateTarget(),
        )

    return submit_plan_for_approval


def make_finish_workflow(ctx: "ContextVariables"):
    """Return a ``finish_workflow`` closure bound to *ctx*.

    Args:
        ctx: The shared session ContextVariables for this team instance.
    """

    def finish_workflow(final_summary: str) -> ReplyResult:
        """【仅在执行阶段使用】所有计划步骤均已完成且 Reviewer 已验证最后一步后，
        调用此工具提交综合分析报告并终止对话。

        将完整的中文分析结论传入 final_summary（用户可直接阅读）。
        调用前必须确认所有步骤均通过 Reviewer 的 [OK] 验证。

        Args:
            final_summary: 引用所有工具真实返回数据的完整化学分析结论。
        """
        ctx["final_summary"] = final_summary
        ctx["state"] = "completed"
        return ReplyResult(
            message=final_summary,
            context_variables=ctx,
            target=TerminateTarget(),
        )

    return finish_workflow

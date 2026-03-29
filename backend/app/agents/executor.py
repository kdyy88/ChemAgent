"""
Executor agents for the ChemAgent multi-agent team.

``create_user_proxy()``
    No-LLM agent that initiates ``a_run_group_chat`` via
    ``DefaultPattern.user_agent``.  Not part of the DefaultPattern's
    internal GroupChat — it drives the chat from outside via
    ``a_initiate_chat(manager, message)``.

    Termination is handled by ``TerminateTarget`` (returned from the
    ``submit_plan_for_approval`` / ``finish_workflow`` control tools)
    rather than by sentinel-text inspection on this agent.
"""

from __future__ import annotations

from autogen import ConversableAgent


def create_user_proxy() -> ConversableAgent:
    """Create the user-proxy agent that initiates group-chat conversations.

    Sits *outside* the DefaultPattern's internal GroupChat (not in
    ``pattern.agents``).  It starts each phase via ``a_initiate_chat``
    or ``a_resume``, then receives the manager's final reply when
    DefaultPattern's ``TerminateTarget`` fires.

    ``max_consecutive_auto_reply=0`` prevents it from automatically sending
    a second message — each phase is exactly one outer exchange.
    """
    return ConversableAgent(
        name="user_proxy",
        llm_config=False,
        human_input_mode="NEVER",
        max_consecutive_auto_reply=0,
        description="User proxy — drives the DefaultPattern chat from outside the group.",
    )


# ── Backwards-compatibility shims ─────────────────────────────────────────────

def create_tool_executor() -> ConversableAgent:
    """Deprecated: DefaultPattern provides its own GroupToolExecutor.

    Kept as a no-op shim so imports in older test files don't break.
    Returns a minimal no-LLM agent that is never added to the group.
    """
    return ConversableAgent(
        name="tool_executor_compat",
        llm_config=False,
        human_input_mode="NEVER",
        description="Deprecated compat shim — not used in DefaultPattern architecture.",
    )


def create_executor() -> ConversableAgent:
    """Deprecated: use create_user_proxy() instead."""
    return create_user_proxy()

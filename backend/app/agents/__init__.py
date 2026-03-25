"""
ChemAgent agent factory.

Provides ``create_agent_pair()`` — the single entry-point for constructing
the ChemBrain (caller) + Executor dual-agent system with all chemistry
tools properly bound via ``register_function``.
"""

from __future__ import annotations

from autogen import ConversableAgent, LLMConfig
from autogen.agentchat import register_function

from app.agents.brain import create_chem_brain
from app.agents.config import build_llm_config, get_resolved_model_name
from app.agents.executor import create_executor
from app.agents.reasoning_client import ReasoningAwareClient
from app.tools import ALL_TOOLS


def create_agent_pair(
    *,
    model: str | None = None,
    llm_config: LLMConfig | None = None,
) -> tuple[ConversableAgent, ConversableAgent]:
    """Create a bound (brain, executor) pair with all tools registered.

    Parameters
    ----------
    model : optional model name override (e.g. ``"gpt-4o"``).
    llm_config : optional pre-built ``LLMConfig``; if given, *model* is
        ignored.

    Returns
    -------
    (brain, executor) — ready for ``executor.run(recipient=brain, ...)``.
    """
    if llm_config is None:
        llm_config = build_llm_config(model)

    brain = create_chem_brain(llm_config)
    executor = create_executor()

    # Dual-bind every tool: brain=caller (decides), executor=executor (runs)
    # NOTE: register_function MUST happen before register_model_client because
    # AG2 re-creates the brain's OpenAIWrapper internally during tool
    # registration, which resets any previously-registered custom clients.
    for tool_fn in ALL_TOOLS:
        register_function(
            tool_fn,
            caller=brain,
            executor=executor,
            name=tool_fn.__name__,
            description=tool_fn.__doc__ or "",
        )

    # Register our reasoning-aware OpenAI client so the brain captures
    # reasoning_content from streaming deltas (o1/o3/o4-mini/deepseek-r1).
    # This MUST be the last step after all register_function calls.
    brain.register_model_client(model_client_cls=ReasoningAwareClient)

    return brain, executor

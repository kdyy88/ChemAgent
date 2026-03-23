from __future__ import annotations

from collections.abc import Callable, Iterable

from autogen import ConversableAgent, LLMConfig
from autogen.tools import Tool

from app.core.tooling import ToolSpec, tool_registry


ToolFilter = Callable[[ToolSpec], bool]


def get_tool_specs(predicate: ToolFilter | None = None) -> list[ToolSpec]:
    specs = tool_registry.list_specs()
    if predicate is None:
        return specs
    return [spec for spec in specs if predicate(spec)]


def describe_tools(specs: Iterable[ToolSpec]) -> str:
    return "\n".join(f"- `{spec.name}`: {spec.description}" for spec in specs)


def format_tool_names(specs: Iterable[ToolSpec]) -> str:
    return ", ".join(f"`{spec.name}`" for spec in specs)


def create_router_agent(
    *,
    name: str,
    system_message: str,
    llm_config: LLMConfig,
) -> ConversableAgent:
    """Create the single-shot Router — a plain ConversableAgent (modern AG2 pattern).

    Replaces the legacy AssistantAgent + UserProxyAgent pair used with
    initiate_chat(). Sessions call agent.run(max_turns=1) for a single-shot
    routing decision, iterating events silently to obtain .summary.
    """
    return ConversableAgent(
        name=name,
        system_message=system_message,
        llm_config=llm_config,
        max_consecutive_auto_reply=1,
        human_input_mode="NEVER",
        code_execution_config=False,
    )


def get_specialist_tools(specs: Iterable[ToolSpec]) -> list[Tool]:
    """Return a list of autogen Tool objects ready for runtime execution.

    These are passed to ``ConversableAgent.run(tools=...)`` so that the
    internal temp-executor (single-agent mode) can execute them.
    """
    return [spec.to_autogen_tool() for spec in specs]


def create_specialist_agent(
    *,
    name: str,
    system_message: str,
    llm_config: LLMConfig,
    specs: Iterable[ToolSpec],
    max_consecutive_auto_reply: int,
) -> tuple[ConversableAgent, list[Tool]]:
    """Create a tool-augmented ConversableAgent (modern single-agent pattern).

    Returns (agent, tools) where:
      - ``agent`` is a ConversableAgent with LLM config. Tools are NOT
        pre-registered here — registering them here AND passing them to
        ``agent.run(tools=...)`` causes a ``Function being overridden``
        UserWarning because ag2's ``_create_or_get_executor`` calls
        ``register_for_llm`` unconditionally on every passed tool.
      - ``tools`` is a list of Tool objects to pass to ``agent.run(tools=...)``.
        ``_create_or_get_executor`` will handle both LLM and execution
        registration in a single pass at run time.
    """
    specs_list = list(specs)
    agent = ConversableAgent(
        name=name,
        system_message=system_message,
        llm_config=llm_config,
        max_consecutive_auto_reply=max_consecutive_auto_reply,
        human_input_mode="NEVER",
        code_execution_config=False,
    )
    tools = get_specialist_tools(specs_list)
    # Do NOT call tool.register_for_llm(agent) here.
    # agent.run(tools=tools) → _create_or_get_executor → registers for both
    # LLM reasoning and execution in one go, avoiding the override warning.
    return agent, tools


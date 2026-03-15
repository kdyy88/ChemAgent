from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from autogen import AssistantAgent, UserProxyAgent

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


def create_assistant_agent(
    *,
    name: str,
    system_message: str,
    llm_config: dict[str, list[dict[str, Any]]],
    max_consecutive_auto_reply: int,
) -> AssistantAgent:
    return AssistantAgent(
        name=name,
        system_message=system_message,
        llm_config=llm_config,
        max_consecutive_auto_reply=max_consecutive_auto_reply,
    )


def create_executor_agent(
    *,
    name: str,
    max_consecutive_auto_reply: int,
    termination_suffix: str = "TERMINATE",
    is_termination_msg: Callable[[dict[str, Any]], bool] | None = None,
) -> UserProxyAgent:
    return UserProxyAgent(
        name=name,
        human_input_mode="NEVER",
        max_consecutive_auto_reply=max_consecutive_auto_reply,
        is_termination_msg=is_termination_msg
        or (lambda payload: (payload.get("content") or "").rstrip().endswith(termination_suffix)),
        code_execution_config=False,
    )


def register_tools(assistant: AssistantAgent, executor: UserProxyAgent, specs: Iterable[ToolSpec]) -> None:
    for spec in specs:
        tool = spec.to_autogen_tool()
        tool.register_for_llm(assistant)
        tool.register_for_execution(executor)


def create_tool_agent_pair(
    *,
    assistant_name: str,
    executor_name: str,
    system_message: str,
    llm_config: dict[str, list[dict[str, Any]]],
    specs: Iterable[ToolSpec],
    max_consecutive_auto_reply: int,
) -> tuple[AssistantAgent, UserProxyAgent]:
    assistant = create_assistant_agent(
        name=assistant_name,
        system_message=system_message,
        llm_config=llm_config,
        max_consecutive_auto_reply=max_consecutive_auto_reply,
    )
    executor = create_executor_agent(
        name=executor_name,
        max_consecutive_auto_reply=max_consecutive_auto_reply,
    )
    register_tools(assistant, executor, specs)
    return assistant, executor

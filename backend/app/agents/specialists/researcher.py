# backend/app/agents/specialists/researcher.py
"""
Researcher specialist agent.

Responsible for:
  - Searching the web and medical/chemical literature via `web_search`
  - Summarising and presenting findings in a structured, user-friendly format

Tools registered: name == "web_search"
"""

from autogen import AssistantAgent, UserProxyAgent

from app.agents.config import build_llm_config
from app.agents.factory import create_tool_agent_pair, describe_tools, get_tool_specs


def _build_system_message() -> str:
    specs = get_tool_specs(lambda spec: spec.name == "web_search")
    tool_descriptions = describe_tools(specs)

    return f"""你是一名专业的化学与药学文献情报专家。你的职责是：
1. 根据给定的研究问题，调用 `web_search` 查询的药物审批、临床试验、分子发现等信息。
2. 对返回结果进行提炼，以清晰的中文列表向用户呈现关键发现（药物名称、适应症、审批年份、来源链接等）。

当前可用工具：
{tool_descriptions}

严格遵守以下规则：
- 只能使用 `web_search` 工具；不得使用其他任何工具。
- 每次搜索后，仔细阅读返回的 `data.results` 列表。
- 如果结果不够充分，可以换关键词重新搜索（最多 2 次）。
- 获得足够信息后，用清晰的中文，列出所有关键发现，然后在消息末尾追加 `TERMINATE`。
- 不要复述原始 JSON；只输出提炼后的人类可读总结。"""


def create_researcher(model: str | None = None) -> tuple[AssistantAgent, UserProxyAgent]:
    """创建并返回 Researcher 专家智能体对 (assistant, executor)。"""
    llm_config = build_llm_config(model)
    specs = get_tool_specs(lambda spec: spec.name == "web_search")
    return create_tool_agent_pair(
        assistant_name="Researcher",
        executor_name="Researcher_Executor",
        system_message=_build_system_message(),
        llm_config=llm_config,
        specs=specs,
        max_consecutive_auto_reply=6,
    )

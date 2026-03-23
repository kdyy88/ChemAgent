# backend/app/agents/specialists/researcher.py
"""
Researcher specialist agent.

Responsible for:
  - Searching the web and medical/chemical literature via `web_search`
  - Summarising and presenting findings in a structured, user-friendly format

Returns (ConversableAgent, list[Tool]) via the modern single-agent pattern:
  agent.run(message=..., tools=tools) — the temp-executor handles tool invocation.
"""

from autogen import ConversableAgent
from autogen.tools import Tool

from app.agents.config import build_llm_config
from app.agents.factory import create_specialist_agent, describe_tools, get_tool_specs


def _build_system_message() -> str:
    specs = get_tool_specs(lambda spec: spec.category == "retrieval")
    tool_descriptions = describe_tools(specs)

    return f"""你是一名专业的化学与药学文献情报专家。你有两个工具，请根据任务类型选择合适的工具：

- `get_smiles_by_name`：当需要获取某化合物的 SMILES 字符串时使用。直接查询 PubChem 权威数据库，速度快且准确，无需网络搜索。
- `web_search`：当需要查询最新药物审批、临床试验进展、文献情报、FDA/EMA 动态等信息时使用。

**工具选择原则**：
- 仅需获取 SMILES → 优先用 `get_smiles_by_name`（速度快、权威）
- 需要最新进展、文献、审批信息 → 使用 `web_search`
- 同时需要 SMILES 和背景信息 → 可依次调用两个工具

当前可用工具：
{tool_descriptions}

严格遵守以下规则：
- 每次搜索后，仔细阅读返回的结果。
- 如果 `web_search` 结果不够充分，可以换关键词重新搜索（最多 2 次）。
- 获得足够信息后，用清晰的中文，列出所有关键发现，然后在消息末尾追加 `TERMINATE`。
- 不要复述原始 JSON；只输出提炼后的人类可读总结。"""


def create_researcher(model: str | None = None) -> tuple[ConversableAgent, list[Tool]]:
    """Create and return the Researcher specialist (agent, tools).

    Pluggable: selects all tools with category="retrieval" from the registry.
    Currently includes:
      - web_search         (Serper web/literature search)
      - get_smiles_by_name (PubChem SMILES retrieval by compound name)
    Any future retrieval tool added to tools/ will be auto-discovered and
    assigned here without editing this file.
    """
    llm_config = build_llm_config(model)
    specs = get_tool_specs(lambda spec: spec.category == "retrieval")
    return create_specialist_agent(
        name="Researcher",
        system_message=_build_system_message(),
        llm_config=llm_config,
        specs=specs,
        max_consecutive_auto_reply=8,  # up to 2 searches + refinement + summary
    )

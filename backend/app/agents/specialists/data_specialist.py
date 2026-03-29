"""
DataSpecialist — PubChem lookup and web search specialist.

This agent owns exactly two tools:
  - ``get_molecule_smiles``  → PubChem canonical SMILES retrieval
  - ``search_web``           → Serper-backed literature / news search

It calls ONE tool per invocation, summarises the outcome in a single sentence,
then emits ``[DONE]`` to signal the router to hand off to the Reviewer.
"""

from __future__ import annotations

from autogen import ConversableAgent

DATA_SPECIALIST_SYSTEM_PROMPT = """你是 ChemAgent 的 **DataSpecialist（数据检索专家）**。

你的专属工具：
• **get_molecule_smiles** — 从 PubChem 检索化合物的标准 SMILES 结构式
• **search_web**          — 搜索最新药物审批、临床试验、文献资料

执行规则：
1. **尽可能并行调用工具**：如果 Planner 分配的多个步骤彻底独立（互不依赖），一次回复中同时发起所有工具调用
2. 工具执行完毕后，用 1-2 句话摘要关键结果
3. 不做计算、不做分析——检索完即结束，控制权自动返回 Planner

**输出格式（简洁）**：
```
[摘要工具返回的关键信息，例如 SMILES、搜索关键发现等]
```

⚠️ 禁止调用 RDKit 相关计算工具，那是 computation_specialist 的职责。
⚠️ 工具失败时输出失败原因，控制权将自动返回 Planner 由其决定是否重试。
⚠️ 不要等待用户确认，立刻调用工具并返回。
"""


def create_data_specialist(llm_config) -> ConversableAgent:
    """Create the DataSpecialist — PubChem + web search, no computation tools."""
    return ConversableAgent(
        name="data_specialist",
        system_message=DATA_SPECIALIST_SYSTEM_PROMPT,
        llm_config=llm_config,
        human_input_mode="NEVER",
        description=(
            "数据检索专家：负责 PubChem SMILES 查询和网络/文献搜索，无 RDKit 计算能力。"
        ),
    )

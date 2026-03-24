# backend/app/agents/specialists/analyst.py
"""
Analyst specialist agent.

Responsible for:
  - Validating SMILES strings using RDKit
  - Computing Lipinski Rule-of-5 parameters (MW, LogP, HBD, HBA)
  - Reporting TPSA as a display-only reference value
  - Generating a 2D structure image embedded in the JSON artifact

Tools registered: name == "analyze_molecule_from_smiles"

Design principle (Agentic UI / Phase 2):
  The underlying computation is identical to the Phase 1 deterministic REST
  endpoint (`POST /api/chem/analyze`). The Analyst agent wraps it as an
  AI-callable tool so the multi-agent pipeline can invoke the same logic
  when the user describes their intent in natural language via the chat UI.
"""

from autogen import AssistantAgent, UserProxyAgent

from app.agents.config import build_llm_config
from app.agents.factory import create_tool_agent_pair, describe_tools, get_tool_specs


def _build_system_message() -> str:
    specs = get_tool_specs(lambda spec: spec.name == "analyze_molecule_from_smiles")
    tool_descriptions = describe_tools(specs)

    return f"""你是一名专业的计算药物化学家，专门评估小分子候选药物的成药性（Drug-likeness）。

你的唯一职责是：调用 `analyze_molecule_from_smiles` 工具，对用户提供的 SMILES 字符串进行分析，
并将结果以清晰的中文总结呈现给用户。

当前可用工具：
{tool_descriptions}

## 工作流程

### 第一步：提取 SMILES
仔细阅读用户消息，找到其中的 SMILES 字符串（通常由字母、数字、括号、等号、井号组成）。
- 如果用户同时提供了化合物名称，提取并作为 `name` 参数传入。
- 如果消息中没有明确的 SMILES，在最终答复中说明需要用户提供 SMILES 格式的结构式，并举例说明格式，然后追加 TERMINATE。

### 第二步：调用工具
将提取的 SMILES 和化合物名称（若有）传入 `analyze_molecule_from_smiles`，**仅调用一次**。

### 第三步：解读结果
根据工具返回，用清晰的中文总结：
- 是否通过 Lipinski 五规则（4 项硬性标准：MW ≤ 500 Da，LogP ≤ 5，HBD ≤ 5，HBA ≤ 10）
- 具体的参数数值
- TPSA 数值（注明为参考值，不计入 Lipinski 评分）
- 如有违规，指出哪项超标及超标幅度
- 最后给出一句简短的成药性判断意见

**严格遵守以下规则：**
- 只能使用 `analyze_molecule_from_smiles` 工具；不得使用任何其他工具。
- 不要复述 JSON 原始内容或 Base64 字符串。
- 完成后在消息末尾追加 TERMINATE。"""


def create_analyst(model: str | None = None) -> tuple[AssistantAgent, UserProxyAgent]:
    """创建并返回 Analyst 专家智能体对 (assistant, executor)。"""
    llm_config = build_llm_config(model)
    specs = get_tool_specs(lambda spec: spec.name == "analyze_molecule_from_smiles")
    return create_tool_agent_pair(
        assistant_name="Analyst",
        executor_name="Analyst_Executor",
        system_message=_build_system_message(),
        llm_config=llm_config,
        specs=specs,
        max_consecutive_auto_reply=5,
    )

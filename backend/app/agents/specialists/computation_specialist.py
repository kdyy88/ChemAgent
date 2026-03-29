"""
ComputationSpecialist — RDKit molecular computation specialist.

This agent owns five tools:
  - ``analyze_molecule``             → descriptors + Lipinski rules
  - ``extract_murcko_scaffold``      → Bemis-Murcko scaffold extraction
  - ``draw_molecule_structure``      → 2-D structure images (batch)
  - ``compute_molecular_similarity`` → Tanimoto fingerprint similarity
  - ``check_substructure``           → SMARTS match + PAINS screen

It calls ONE tool per invocation, summarises in a sentence, then emits
``[DONE]`` to hand off to the Reviewer.
"""

from __future__ import annotations

from autogen import ConversableAgent

COMPUTATION_SPECIALIST_SYSTEM_PROMPT = """你是 ChemAgent 的 **ComputationSpecialist（分子计算专家）**。

你的专属工具：
• **analyze_molecule**             — 计算 Lipinski 五规则、QED、SA Score、TPSA 等 15+ 项描述符
• **extract_murcko_scaffold**      — 提取 Bemis-Murcko 骨架和通用碳骨架
• **draw_molecule_structure**      — 批量生成 2D 分子结构图（PNG）
• **compute_molecular_similarity** — 计算 Morgan/ECFP4 指纹 Tanimoto 相似度
• **check_substructure**           — SMARTS 子结构匹配 + PAINS 毒性筛查

执行规则：
1. **尽可能并行调用工具**：如果 Planner 分配有多个机于同一 SMILES 的独立计算任务，一次回复中同时发起所有工具调用！
   示例：同时需要 analyze_molecule + extract_murcko_scaffold 时，一条回复同时调用两个工具。
2. 需要 SMILES 时，直接使用对话历史中 data_specialist 已检索到的 SMILES
3. 工具执行完毕后，用 1-2 句话摘要关键计算结果
4. 执行完毕即结束，控制权自动返回 Planner

**输出格式（简洁）**：
```
[摘要关键数值或发现，例如 MW/LogP/Tanimoto 等]
```

⚠️ 禁止调用 get_molecule_smiles 或 search_web——数据检索是 data_specialist 的职责。
⚠️ 工具失败时输出失败原因，控制权将自动返回 Planner 由其决定是否重试。
⚠️ 不要等待用户确认，立刻调用工具并返回。
"""


def create_computation_specialist(llm_config) -> ConversableAgent:
    """Create the ComputationSpecialist — all RDKit tools, no data retrieval."""
    return ConversableAgent(
        name="computation_specialist",
        system_message=COMPUTATION_SPECIALIST_SYSTEM_PROMPT,
        llm_config=llm_config,
        human_input_mode="NEVER",
        description=(
            "分子计算专家：负责所有 RDKit 分子计算（描述符/骨架/相似度/子结构），"
            "无 PubChem 或网络搜索权限。"
        ),
    )

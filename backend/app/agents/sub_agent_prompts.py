"""Sub-Agent Persona System Prompts
=====================================

Factory functions that produce mode-specific system prompts for sub-agents.
Each sub-agent type gets a Persona that constrains its behaviour to its role,
prevents capability leakage, and enforces the anti-recursion rule.

Design
------
- Prompts are intentionally concise — sub-agents should not mirror the full
  root-agent prompt.  The root agent handles SMILES consistency, task tracking,
  and HITL routing; sub-agents have narrower remits.
- All prompts include the anti-recursion reminder and artifact-pointer rule.
- The ``custom`` mode injects the caller's instructions verbatim after a safety
  header that re-affirms the depth=1 limit.
"""

from __future__ import annotations

from app.agents.tool_registry import SubAgentMode


# ── Shared fragments ──────────────────────────────────────────────────────────

_ANTI_RECURSION = (
    "【硬约束】你是一个子智能体（depth=1）。"
    "你不能调用 tool_run_sub_agent，不能再委派子任务，不能向用户发送澄清请求。"
    "如果任务确实需要更多信息，请在回答中明确说明缺失的内容，由调用者决策。"
)

_ARTIFACT_RULE = (
    "【工件规则】当工具产生 SDF/PDB 等大型文件时，只输出指针（如 art_id=xxx），"
    "严禁在文本回答中直接粘贴坐标数据。"
)

_SMILES_RULE = (
    "【SMILES 规则】若工具返回了新 SMILES（如 cleaned_smiles / canonical_smiles），"
    "后续工具调用必须优先使用该新 SMILES，不可回退到原始输入。"
)

_FOOTER = f"\n\n{_ANTI_RECURSION}\n{_ARTIFACT_RULE}\n{_SMILES_RULE}"


# ── Mode-specific prompts ─────────────────────────────────────────────────────

def _explore_prompt() -> str:
    return (
        "<identity>\n"
        "你是 ChemAgent Explore（探索子智能体）。"
        "你的职责是收集和汇总信息：查询分子性质、文献数据、数据库记录。\n"
        "你只做只读调研，不产生任何副作用，不生成 3D 构象，不修改分子结构。\n"
        "完成后，以结构化的 Markdown 格式返回调研摘要，包含：数据来源、关键数值、你的解读。\n"
        "</identity>"
        + _FOOTER
    )


def _plan_prompt() -> str:
    return (
        "<identity>\n"
        "你是 ChemAgent Plan（规划子智能体）。"
        "你的职责是将一个复杂的生化计算任务分解为可执行的结构化计划。\n\n"
        "输出格式要求：\n"
        "1. 严格输出 Markdown，使用编号列表。\n"
        "2. 每个步骤必须注明：使用的工具、预期输入、预期输出。\n"
        "3. 不调用任何工具，纯粹基于你的化学信息学知识进行逻辑推演。\n"
        "4. 如果任务参数不足，在计划末尾单独列出「数据缺口」小节。\n"
        "</identity>"
        + _FOOTER
    )


def _general_prompt() -> str:
    return (
        "<identity>\n"
        "你是 ChemAgent General（通用执行子智能体）。"
        "你被分配了一个明确的生化计算子任务。使用可用工具完成它，然后输出简洁的结论报告。\n\n"
        "工作原则：\n"
        "1. 采用 ReAct 工作流：先思考，再调用工具，再分析结果，循环直至完成。\n"
        "2. 同一步骤可并行调用多个独立工具。\n"
        "3. 对每个工具结果做简短验证（is_valid, found 等标志位）再继续。\n"
        "4. 最终回复：极简专业。汇报计算结果，引用关键数值，指出 artifact 指针。\n"
        "</identity>"
        + _FOOTER
    )


def _custom_prompt(custom_instructions: str) -> str:
    if custom_instructions.strip():
        body = custom_instructions.strip()
    else:
        body = (
            "你是一个专项化学信息学子智能体。"
            "按照上下文中的任务描述执行，使用可用工具，返回简洁结论。"
        )
    return (
        "<identity>\n"
        f"{body}\n"
        "</identity>"
        + _FOOTER
    )


# ── Public factory ─────────────────────────────────────────────────────────────


def get_sub_agent_prompt(
    mode: SubAgentMode,
    custom_instructions: str = "",
) -> str:
    """Return the system prompt for a sub-agent of the given *mode*.

    Parameters
    ----------
    mode:
        Sub-agent operating mode.
    custom_instructions:
        Only used when ``mode == SubAgentMode.custom``.  Replaces the default
        identity block with the caller's instructions.
    """
    match mode:
        case SubAgentMode.explore:
            return _explore_prompt()
        case SubAgentMode.plan:
            return _plan_prompt()
        case SubAgentMode.general:
            return _general_prompt()
        case SubAgentMode.custom:
            return _custom_prompt(custom_instructions)
        case _:
            return _general_prompt()

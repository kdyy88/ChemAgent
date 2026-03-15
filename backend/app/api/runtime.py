from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from autogen.io.run_response import RunResponseProtocol


@dataclass
class AgentTeam:
    manager: object
    router: object
    router_trigger: object
    visualizer: object
    visualizer_executor: object
    researcher: object
    researcher_executor: object


@dataclass
class SpecialistSummary:
    label: str
    success: bool
    summary: str
    error: str | None = None
    generated_image: bool = False


@dataclass
class MultiAgentRunPlan:
    routing_rationale: str
    phase2_items: list[tuple[str, RunResponseProtocol]]
    synthesis_factory: Callable[[list[SpecialistSummary]], RunResponseProtocol]


def format_turn_history(history: list[dict[str, str]], limit: int = 3) -> str:
    if not history:
        return ""

    lines = ["历史对话上下文："]
    for index, turn in enumerate(history[-limit:], 1):
        lines.append(f"第{index}轮 - 用户：{turn['user']}")
        lines.append(f"第{index}轮 - 结果：{turn['result']}")
    return "\n".join(lines)


def build_synthesis_prompt(
    *,
    original_prompt: str,
    routing_rationale: str,
    summaries: list[SpecialistSummary],
    is_general: bool = False,
) -> str:
    if is_general:
        return (
            f"用户问题：{original_prompt}\n\n"
            "这是一个通用问题（能力介绍、使用方式或闲聊），无需调用专家工具，请直接用中文友好地回答。\n"
            "你是 ChemAgent，一个化学科研 AI 助手，具备：\n"
            "- Visualizer 专家：检索化合物 SMILES（PubChem）并生成 2D 分子结构图（RDKit）\n"
            "- Researcher 专家：搜索最新药物审批、临床试验、文献情报（Web Search）\n"
            "回答时语气自然，不要列举工具调用细节。"
        )

    visualizer_succeeded = any(
        summary.label == "Visualizer" and summary.success and summary.generated_image
        for summary in summaries
    )
    lines = [f"用户原始问题：{original_prompt}"]
    if routing_rationale:
        lines.append(f"路由决策逻辑：{routing_rationale}")
    lines.append("2D结构图已成功生成" if visualizer_succeeded else "Visualizer 未运行，本轮没有生成任何 2D 结构图")
    lines.extend(["", "各专家执行结果汇总："])

    for summary in summaries:
        icon = "✅" if summary.success else "❌"
        detail = summary.summary if summary.success else f"错误：{summary.error or '未知错误'}"
        lines.append(f"- {summary.label} 专家 {icon}：{detail}")

    lines.extend(["", "请根据以上专家报告，向用户提供专业、诚实的综合回答。"])
    return "\n".join(lines)

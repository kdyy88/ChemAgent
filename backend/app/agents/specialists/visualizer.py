# backend/app/agents/specialists/visualizer.py
"""
Visualizer specialist agent.

Responsible for batch-drawing 2D molecular structures for all requested compounds
in a SINGLE tool call via `draw_molecules_by_name`.

Returns (ConversableAgent, list[Tool]) via the modern single-agent pattern:
  agent.run(message=..., tools=tools) — the temp-executor handles tool invocation.
"""

from autogen import ConversableAgent
from autogen.tools import Tool

from app.agents.config import build_llm_config
from app.agents.factory import create_specialist_agent, describe_tools, format_tool_names, get_tool_specs


def _build_system_message() -> str:
    specs = get_tool_specs(lambda spec: spec.category == "visualization")
    tool_descriptions = describe_tools(specs)
    tool_names = format_tool_names(specs)

    return f"""你是一名专业的化学结构可视化专家。你的职责是将任务中所有化合物绘制为 2D 结构图，确保一张不漏。

当前可用工具：
{tool_descriptions}

## 工具选择原则（优先判断）
- 任务中包含化合物名称（中文/英文药名）→ 使用 `draw_molecules_by_name`（可批量、支持 PubChem 检索）
- 任务中包含 SMILES 字符串（含 =、(、)、数字、小写字母等特征字符）→ 使用 `generate_2d_image_from_smiles`

## 使用 draw_molecules_by_name 的工作流程

### 第一步：名称规范化（调用工具前必做）
- 将中文药名翻译为对应英文 INN/USAN 批准名（如「阿司匹林」→「Aspirin」）。
- 对不确定的名称，优先采用 INN 国际非专利名，其次 IUPAC 系统名。

### 第二步：一次性批量调用
将全部规范化后的英文名合并为逗号分隔字符串，**一次调用** `draw_molecules_by_name`：
示例：`draw_molecules_by_name(chemical_names="Gepotidacin, Zoliflodacin, Sulopenem")`
**绝对禁止**逐个循环调用，必须一次传入所有名称。

### 第三步：处理部分失败
若工具返回 `data.failed`（非空列表），仅对失败项换用替代名再调用一次（最多一次补充重试）。
若仍失败，在总结中逐条注明原因，不再重试。

## 使用 generate_2d_image_from_smiles 的工作流程
直接将用户提供的 SMILES 字符串和化合物名称（若有）传入工具，**仅调用一次**即可。

## 完成
所有可处理的结构图均已生成后，用一句简洁中文总结，并在末尾追加 `TERMINATE`。

## 通用规则
- 只使用以下工具：{tool_names}。
- 不要复述冗长 JSON 或 Base64 内容。"""


def create_visualizer(model: str | None = None) -> tuple[ConversableAgent, list[Tool]]:
    """Create and return the Visualizer specialist (agent, tools).

    Pluggable: selects all tools with category="visualization" from the registry.
    Currently includes:
      - draw_molecules_by_name  (name → PubChem lookup → 2D image)
      - generate_2d_image_from_smiles  (SMILES → 2D image, no network)
    Any future visualization tool added to tools/ will be auto-discovered and
    assigned here without editing this file.
    """
    llm_config = build_llm_config(model)
    specs = get_tool_specs(lambda spec: spec.category == "visualization")
    return create_specialist_agent(
        name="Visualizer",
        system_message=_build_system_message(),
        llm_config=llm_config,
        specs=specs,
        max_consecutive_auto_reply=8,  # up to 2 batch calls + 1 retry + summary
    )

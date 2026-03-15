# backend/app/agents/specialists/visualizer.py
"""
Visualizer specialist agent.

Responsible for:
  - Retrieving canonical SMILES from PubChem via `get_smiles_by_name`
  - Generating 2D molecular structure images via `generate_2d_image_from_smiles`

Tools registered: category in ("visualization", "retrieval") AND name != "web_search"
"""

from autogen import AssistantAgent, UserProxyAgent

from app.agents.config import get_llm_config
from app.agents.factory import create_tool_agent_pair, describe_tools, format_tool_names, get_tool_specs


def _build_system_message() -> str:
    specs = get_tool_specs(
        lambda spec: spec.category in ("visualization", "retrieval") and spec.name != "web_search"
    )
    tool_descriptions = describe_tools(specs)
    tool_names = format_tool_names(specs)

    return f"""你是一名专业的化学结构可视化专家。你的唯一职责是：
1. 根据给定的化合物名称（中文或英文），调用 `get_smiles_by_name` 从 PubChem 检索标准 Canonical SMILES。
2. 获得 SMILES 后，调用 `generate_2d_image_from_smiles(smiles=..., name=「化合物英文名称」)` 生成高清 2D 结构图。必须将化合物英文名称作为 `name` 参数传入。

当前可用工具：
{tool_descriptions}

严格遵守以下规则：
- 不捧造 SMILES；必须通过检索工具获取依据。
- `get_smiles_by_name` 成功后，立即调用绘图工具，不可停止。
- 绘图时必须传入 `name` 参数（化合物英文名）作为图片标题。
- 工具返回 `status = "error"` 时，结合 `retry_hint` 换名再试（如中文名→英文名）。
- 任一工具返回内含 `artifacts` 的成功结果后，用一句简洁中文告知任务完成，并在末尾追加 `TERMINATE`。
- 只使用以下工具：{tool_names}。
- 不要复述冗长 JSON 或 Base64 内容。"""


def create_visualizer() -> tuple[AssistantAgent, UserProxyAgent]:
    """创建并返回 Visualizer 专家智能体对 (assistant, executor)。"""
    llm_config = get_llm_config()
    specs = get_tool_specs(
        lambda spec: spec.category in ("visualization", "retrieval") and spec.name != "web_search"
    )
    return create_tool_agent_pair(
        assistant_name="Visualizer",
        executor_name="Visualizer_Executor",
        system_message=_build_system_message(),
        llm_config=llm_config,
        specs=specs,
        max_consecutive_auto_reply=6,
    )

# backend/app/agents/specialists/visualizer.py
"""
Visualizer specialist agent.

Responsible for batch-drawing 2D molecular structures for all requested compounds
in a SINGLE tool call via `draw_molecules_by_name`.

Tools registered: name == "draw_molecules_by_name"
"""

from autogen import AssistantAgent, UserProxyAgent

from app.agents.config import build_llm_config
from app.agents.factory import create_tool_agent_pair, describe_tools, format_tool_names, get_tool_specs


def _build_system_message() -> str:
    specs = get_tool_specs(lambda spec: spec.name == "draw_molecules_by_name")
    tool_descriptions = describe_tools(specs)
    tool_names = format_tool_names(specs)

    return f"""你是一名专业的化学结构可视化专家。你的唯一职责是，将任务中所有化合物逐一绘制 2D 结构图，确保一张不漏。

当前可用工具：
{tool_descriptions}

## 工作流程

### 第一步：名称规范化（调用工具前必做）
在调用任何工具前，先对每个化合物名称进行反思：
- 将中文药名翻译为对应英文 INN/USAN 批准名（如「阿司匹林」→「Aspirin」）。
- 检查拼写与大小写（如 "Gepotidacin" 而非 "Gepotidacin"）。
- 对不确定的名称，优先采用 INN 国际非专利名，其次 IUPAC 系统名。

### 第二步：一次性批量调用
将全部规范化后的英文名合并为逗号分隔字符串，**一次调用** `draw_molecules_by_name`：
示例：`draw_molecules_by_name(chemical_names="Gepotidacin, Zoliflodacin, Sulopenem, Cefiderocol, Lefamulin")`

**绝对禁止**逐个循环调用，必须一次传入所有名称。

### 第三步：处理部分失败
若工具返回 `data.failed`（非空列表），说明有名称未能处理：
- `data.failed` 中每项格式为 `{{"name": "原名称", "reason": "失败原因"}}`，可精确知道是哪个名称出错。
- 已成功的结构图（`artifacts`）已经生成，**无需重新提交**成功项。
- 仅对失败项逐一反思：根据 `reason` 判断是名称问题还是数据库收录问题，换用替代名（别名、IUPAC 名、CAS 登记名等），组成新的逗号分隔列表，**再调用一次**工具处理剩余失败项。
- 若补充调用后仍有名称无法处理，在最终总结中逐条注明哪个化合物未能绘制及原因，不再重试。

### 第四步：完成
所有可处理的结构图均已生成后，用一句简洁中文总结（完成数量 + 任何未能处理的名称），并在末尾追加 `TERMINATE`。

## 其他规则
- 只使用以下工具：{tool_names}。
- 不要复述冗长 JSON 或 Base64 内容。
- 最多补充重试一次，避免无限循环。"""


def create_visualizer(model: str | None = None) -> tuple[AssistantAgent, UserProxyAgent]:
    """创建并返回 Visualizer 专家智能体对 (assistant, executor)。"""
    llm_config = build_llm_config(model)
    specs = get_tool_specs(lambda spec: spec.name == "draw_molecules_by_name")
    return create_tool_agent_pair(
        assistant_name="Visualizer",
        executor_name="Visualizer_Executor",
        system_message=_build_system_message(),
        llm_config=llm_config,
        specs=specs,
        max_consecutive_auto_reply=4,
    )

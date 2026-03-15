# backend/app/agents/manager.py
"""
Manager agent — routes user prompts to specialist agents and synthesises their results.

Routing phase:  Uses a session-persistent Router AssistantAgent (pre-initialised in
                AgentTeam; history is cleared on every call via clear_history=True).
Synthesis phase: Uses the full-model Manager AssistantAgent (also session-persistent,
                 history is KEPT across turns so Manager has full multi-turn context).

The Manager never executes tools itself; all tool work is delegated to specialists.
"""

import json
import re

from autogen import AssistantAgent, UserProxyAgent

from app.agents.config import get_fast_llm_config, build_llm_config
from app.agents.factory import create_assistant_agent


# ── Routing ───────────────────────────────────────────────────────────────────

_ROUTING_SYSTEM_MESSAGE = """你是一个化学科研主管，负责将用户的问题分发给正确的专家助手。

可用的专家：
- "visualizer"：负责化学结构检索与 2D 绘图（使用 PubChem 和 RDKit 工具）
- "researcher"：负责搜索最新药物审批、临床进展、文献情报（使用 Web Search 工具）

你必须只输出一个 JSON 对象，格式如下，不要输出任何其他内容：
{
  "route": ["visualizer"],           // 必填，数组，可包含 "visualizer"、"researcher" 或两者
  "refined_prompts": {
    "visualizer": "...",             // 仅当 route 含 visualizer 时必填
    "researcher": "..."              // 仅当 route 含 researcher 时必填
  },
  "routing_rationale": "..."         // 简短的中文路由理由（1-2句话）
}

路由判断规则：
- 画结构/绘图/SMILES/分子式/化合物/药物结构 → ["visualizer"]
- 新药/最新进展/审批/论文/临床试验/FDA/EMA → ["researcher"]
- 既要查新药又要画结构 → ["visualizer", "researcher"]
- 纯化学性质计算（分子量/logP 等）→ ["visualizer"]
- 询问你是谁/你能干什么/你有什么功能/如何使用/功能介绍/问候语/闲聊 → ["general"]
- 其他通用化学问题 → ["visualizer"]

**消歧义规则（最高优先级）**
如果用户的问题含模糊引用（"相关分子"、"它们"、"这些药物"、"那个化合物"、
"第一个"、"上面提到的"等），必须结合消息开头的“历史对话上下文”将模糊引用
扩展为具体的化合物/药物名称，写入 refined_prompts。
示例：若历史显示上轮有 Amivantamab、Adagrasib，用户问“画出相关分子”，则：
  refined_prompts.visualizer = "请分别绘制 Amivantamab、Adagrasib 的 2D 分子结构"

只输出 JSON，不要有多余文字。"""


_STRIP_FENCES_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _fallback_routing(reason: str) -> dict:
    return {
        "route": ["general"],
        "refined_prompts": {},
        "routing_rationale": f"fallback:{reason}",
    }


def _load_first_json_object(text: str) -> dict | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return data if isinstance(data, dict) else None
    return None


def parse_routing_decision(text: str) -> dict:
    """从 Manager 路由阶段的输出中解析 JSON 路由决策。

    健壮性策略（按优先级）：
    1. 直接解析完整 JSON
    2. 剥离 Markdown 代码围栏（```json ... ``` 或 ``` ... ```）
    3. 扫描并解析首个 JSON 对象
    4. 任何失败 → fallback 到 general
    """
    raw = (text or "").strip()

    if not raw:
        return _fallback_routing("empty")

    # Strategy 1: direct parse
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None

    # Strategy 2: unwrap Markdown fences, then re-parse
    if not isinstance(data, dict):
        fence_match = _STRIP_FENCES_RE.search(raw)
        candidate = fence_match.group(1) if fence_match else raw
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            # Strategy 3: scan for first JSON object
            data = _load_first_json_object(candidate)

    if not isinstance(data, dict):
        return _fallback_routing("json-parse")

    route = data.get("route", ["general"])
    if not isinstance(route, list) or not route:
        route = ["general"]
    # Validate entries
    valid = {"visualizer", "researcher", "general"}
    route = [r for r in route if r in valid] or ["general"]

    refined = data.get("refined_prompts", {})
    if not isinstance(refined, dict):
        refined = {}

    return {
        "route": route,
        "refined_prompts": refined,
        "routing_rationale": str(data.get("routing_rationale", "")),
    }


def create_routing_agent() -> tuple[AssistantAgent, UserProxyAgent]:
    """创建路由 Agent 对。

    供 AgentTeam 在 session 初始化时调用一次，之后通过 clear_history=True
    在每轮路由中重置会话状态，避免每次对话重建对象的开销。
    """
    fast_config = get_fast_llm_config()

    router = create_assistant_agent(
        name="Manager_Router",
        system_message=_ROUTING_SYSTEM_MESSAGE,
        llm_config=fast_config,
        max_consecutive_auto_reply=1,
    )

    trigger = UserProxyAgent(
        name="Manager_Router_Trigger",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=0,  # Single-shot: just collect the first reply
        is_termination_msg=lambda x: True,  # Stop immediately after first reply
        code_execution_config=False,
    )

    return router, trigger


# ── Synthesis ─────────────────────────────────────────────────────────────────
# Exported so sessions.py can pass it directly to the OpenAI streaming call
# without going through the AG2 agent wrapper.
SYNTHESIS_SYSTEM_MESSAGE = """你是首席化学科学家，也是本次对话的主持人。各专家助手已完成各自的调研与工具任务，现在由你向用户给出最终的综合答案。

**格式规范（严格执行）**
- 使用标准 Markdown：药物名/化合物名用 **加粗**，多条结果用编号列表（1. 2. 3.）
- 每个化合物条目结构：**名称** — 适应症（一句话）— 靶点或机制亮点
- 如有多类信息（文献 + 结构图），用小标题清晰分隔
- 回答末尾加一句专业洞见，总结这批化合物的科学趋势（靶点布局、精准医疗方向等）

**内容规范（严格执行）**
- 直接给出结论，严禁出现任何工具痕迹语言：
  × "根据工具返回" × "根据专家报告" × "以下是搜索结果" × "STUB"
- **结构图规则（最高优先级，严禁违反）**：
  √ 仅当合成提示中明确写有 「2D结构图已成功生成」时，才可提及结构图，但不要尝试通过Markdown格式渲染图片，
- 部分失败时诚实简洁地说明（如："Amivantamab 结构渲染遇到了化学价键错误，其余均已正常生成。"）
- 不复述 JSON、Base64 或原始摘要文档
- 完成后在消息末尾追加 TERMINATE"""


def create_manager(model: str | None = None) -> AssistantAgent:
    """创建 Manager synthesis Agent（使用完整模型，由 session 持久化复用）。

    llm_config 中不设置 max_tokens，使用模型默认上下文窗口，确保多轮合成时
    Manager 不会因 Token 截断而丢失历史上下文。
    """
    llm_config = build_llm_config(model)

    manager = create_assistant_agent(
        name="Manager",
        system_message=SYNTHESIS_SYSTEM_MESSAGE,
        llm_config=llm_config,
        max_consecutive_auto_reply=3,
    )

    return manager


# ── Local test ────────────────────────────────────────────────────────────────

def _run_routing_test(prompt: str, history_context: str = "") -> dict:
    router, trigger = create_routing_agent()
    full_prompt = (history_context + "\n\n当前用户问题：" + prompt) if history_context else prompt
    trigger.initiate_chat(router, message=full_prompt, summary_method="last_msg", clear_history=True)
    last = router.last_message() or {}
    content = last.get("content", "")
    result = parse_routing_decision(content)
    print(f"\n[Router] Raw output:\n{content}")
    print(f"\n[Router] Parsed decision: {result}")
    return result


if __name__ == "__main__":
    print("=== Test 1: 画结构 ===")
    _run_routing_test("帮我画一个阿司匹林的结构式")

    print("\n=== Test 2: 查新药 ===")
    _run_routing_test("最近 FDA 批准了哪些针对肺癌的新药？")

    print("\n=== Test 3: 复合任务 ===")
    _run_routing_test("帮我找最新的 FDA 批准肺癌药物，并画出它们的 2D 结构")

    print("\n=== Test 4: 消歧义 ===")
    _history = (
        "历史对话上下文：\n"
        "第1轮 - 用户：最近有什么新的抗肿瘺药物？\n"
        "第1轮 - 结果：找到 Amivantamab (NSCLC/EGFR外显子20插入)、"
        "Adagrasib (NSCLC/KRAS G12C)、Sotorasib (NSCLC/KRAS G12C)"
    )
    _run_routing_test("可以画出相关分子吗？", history_context=_history)

    print("\n=== Test 5: Markdown 围栏剖离 ===")
    _fenced = (
        "```json\n"
        '{"route": ["researcher"], "refined_prompts": {"researcher": "query"}, '
        '"routing_rationale": "test"}\n'
        "```"
    )
    print(parse_routing_decision(_fenced))

# backend/app/agents/manager.py
"""
Manager agent — routes user prompts to specialist agents and synthesises results.

Routing phase:  Single ConversableAgent (modern single-shot .run() pattern).
                History is cleared on every call via clear_history=True.
                Sessions call router.run(max_turns=1) and exhaust events to get .summary.
Synthesis phase: Raw AsyncOpenAI streaming call in event_bridge.stream_synthesis_async()
                 — no AG2 agent object is used. SYNTHESIS_SYSTEM_MESSAGE is exported
                 from here so sessions.py can pass it directly to the OpenAI client.

create_manager() and sanitize_messages() were removed in the v2 refactor (dead code).
"""

import json
import re

from autogen import ConversableAgent

from app.agents.config import get_fast_llm_config
from app.agents.factory import create_router_agent


# ── Routing ───────────────────────────────────────────────────────────────────

_ROUTING_SYSTEM_MESSAGE = """你是一个化学科研主管，负责将用户的问题分发给正确的专家助手。

可用的专家：
- "visualizer"：负责化学结构可视化，拥有两个工具：
    1. 按化合物名称（中英文）检索 PubChem 并批量生成 2D 结构图
    2. 直接将用户提供的 SMILES 字符串渲染为 2D 结构图
- "researcher"：负责信息检索，拥有两个工具：
    1. 搜索最新药物审批、临床进展、文献情报（Web Search）
    2. 通过化合物名称直接查询 PubChem 获取 SMILES（适合无需绘图、仅需 SMILES 的场景）
- "analyst"：负责验证 SMILES、计算 Lipinski 五规则（MW/LogP/HBD/HBA）以及极性表面积 TPSA（使用 RDKit 工具）

你必须只输出一个 JSON 对象，格式如下，不要输出任何其他内容：
{
  "route": ["visualizer"],           // 必填，数组，可包含 "visualizer"、"researcher"、"analyst" 或多者组合
  "refined_prompts": {
    "visualizer": "...",             // 仅当 route 含 visualizer 时必填
    "researcher": "...",             // 仅当 route 含 researcher 时必填
    "analyst": "..."                 // 仅当 route 含 analyst 时必填
  },
  "routing_rationale": "..."         // 简短的中文路由理由（1-2句话）
}

路由判断规则（按优先级从高到低）：
- 用户提供了 SMILES 字符串（含 =、(、)、数字、小写字母等 SMILES 特征字符）且要求"分析"/"计算"/"Lipinski"/"分子量"/"LogP"/"成药性" → ["analyst"]
- 用户提供了 SMILES 字符串且同时要求绘图 → ["analyst", "visualizer"]
- 用户提供了 SMILES 字符串且同时要求绘图+分析 → ["analyst", "visualizer"]
- 用户提供化合物名称，仅需获取其 SMILES（不需绘图）→ ["researcher"]（researcher 用 get_smiles_by_name 工具）
- 画结构/绘图（按化合物名称）/化合物名称查询并可视化 → ["visualizer"]
- 新药/最新进展/审批/论文/临床试验/FDA/EMA → ["researcher"]
- 既要查新药进展又要画结构 → ["visualizer", "researcher"]
- 询问你是谁/你能干什么/你有什么功能/如何使用/功能介绍/问候语/闲聊 → ["general"]
- 其他通用化学问题 → ["visualizer"]

**SMILES 识别规则（最高优先级）**
消息中若出现符合 SMILES 格式的字符串（如 CC(C)Cc1ccc(cc1)C(C)C(=O)O），
无论用户是否明确说"SMILES"，均视为提供了结构式，应路由到 analyst（如需分析）或 visualizer（如需绘图）。

**消歧义规则**
如果用户含模糊引用（"相关分子"、"它们"、"这些药物"等），结合历史对话上下文将模糊引用
扩展为具体的化合物/药物名称，写入 refined_prompts。

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
    valid = {"visualizer", "researcher", "analyst", "general"}
    route = [r for r in route if r in valid] or ["general"]

    refined = data.get("refined_prompts", {})
    if not isinstance(refined, dict):
        refined = {}

    return {
        "route": route,
        "refined_prompts": refined,
        "routing_rationale": str(data.get("routing_rationale", "")),
    }


def create_routing_agent() -> ConversableAgent:
    """创建路由 Agent（现代单智能体模式）。

    替代原来的 AssistantAgent + UserProxyAgent 对 + initiate_chat() 方案。
    Sessions 通过 agent.run(max_turns=1, silent=True) 获取单次路由决策，
    然后遍历 result.events 使 result.summary 可用，无需 UserProxyAgent 触发器。
    """
    fast_config = get_fast_llm_config()
    return create_router_agent(
        name="Manager_Router",
        system_message=_ROUTING_SYSTEM_MESSAGE,
        llm_config=fast_config,
    )


# ── Synthesis ─────────────────────────────────────────────────────────────────
# SYNTHESIS_SYSTEM_MESSAGE is exported and passed directly to the AsyncOpenAI
# streaming call in event_bridge.stream_synthesis_async() — no AG2 agent is used
# for synthesis. This is intentional: AG2 has no async streaming WebSocket
# output interface, so we bypass it for the final synthesis phase only.
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
  × 也严禁创建任何指向结构图的 Markdown 超链接（如 [链接至结构图](...)、[查看结构](...)），结构图由前端独立渲染，Markdown 中完全不提即可（直接说"结构图已在下方显示"即可），
- 部分失败时诚实简洁地说明（如："Amivantamab 结构渲染遇到了化学价键错误，其余均已正常生成。"）
- 不复述 JSON、Base64 或原始摘要文档
- 完成后在消息末尾追加 TERMINATE"""


# ── Local test ────────────────────────────────────────────────────────────────

def _run_routing_test(prompt: str, history_context: str = "") -> dict:
    router = create_routing_agent()
    full_prompt = (history_context + "\n\n当前用户问题：" + prompt) if history_context else prompt
    result = router.run(
        message=full_prompt,
        max_turns=1,
        clear_history=True,
        summary_method="last_msg",
        silent=True,
    )
    # Exhaust events so result.summary is populated
    for _ in result.events:
        pass
    content = result.summary or ""
    decision = parse_routing_decision(content)
    print(f"\n[Router] Raw output:\n{content}")
    print(f"\n[Router] Parsed decision: {decision}")
    return decision


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

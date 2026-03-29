"""
Reviewer — independent result validator separating execution from verification.

The Reviewer is the quality-control gate between tool execution and progress.
It holds no tools and has no planning authority.  Its sole job is to inspect
the most-recent tool execution result and decide:

  [OK]                         — result is valid; Planner may proceed
  [RETRY: data_specialist]     — DataSpecialist's call failed / bad result
  [RETRY: computation_specialist] — ComputationSpecialist call failed / bad result

By separating *check authority* from *execution authority*, ChemAgent avoids
the "self-certifying hallucination" trap where an agent validates its own output.
"""

from __future__ import annotations

from autogen import ConversableAgent

REVIEWER_SYSTEM_PROMPT = """你是 ChemAgent 的 **Reviewer（质检员）**，执行权与检查权分离的核心。

你的唯一职责：检验 **最近一次** 工具执行结果是否合格。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
判断标准
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 工具返回 status=success 且摘要合理 → **合格**
• 工具返回 status=error 或摘要明显有误 → **不合格**
• 专家的简短描述与工具结果基本一致 → **合格**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出格式（严格只输出以下三种之一，不要多余解释）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

合格时：
```
[OK]
```

data_specialist 需重试时：
```
[RETRY: data_specialist] 原因（一句话）
```

computation_specialist 需重试时：
```
[RETRY: computation_specialist] 原因（一句话）
```

⚠️ 你只看最近一次工具执行（`tool.result` / `ExecutedFunctionEvent`）的 status 和 summary。
⚠️ 不要重新计算，不要修改结果，不要决定任务是否全部完成——那是 Planner 的职责。
⚠️ 不要对工具结果做补充分析，保持输出极简。
"""


def create_reviewer(llm_config) -> ConversableAgent:
    """Create the Reviewer — stateless quality-control gate, no tools."""
    return ConversableAgent(
        name="reviewer",
        system_message=REVIEWER_SYSTEM_PROMPT,
        llm_config=llm_config,
        human_input_mode="NEVER",
        description=(
            "质检员：独立验证每次工具执行结果的正确性，"
            "将检查权与执行权分离以防止幻觉自认证。"
        ),
    )

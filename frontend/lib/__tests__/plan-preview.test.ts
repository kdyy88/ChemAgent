import { describe, expect, it } from 'vitest'
import { parsePlanPreview } from '../plan-preview'

describe('parsePlanPreview', () => {
  it('extracts goal, stage titles, and intents from plan markdown', () => {
    const markdown = `# 总体生化目标
建立一条用于候选分子筛选的验证路径。

# 执行管线 (Pipeline)
## 阶段 1：收集靶点约束
* **动作意图**: 汇总靶点约束并形成筛选边界。
* **依赖工件 (Inputs)**: 无
* **挂载工具 (Required Tools)**: database_lookup
* **预期产出 (Outputs)**: 靶点约束摘要

## 阶段 2：筛选候选分子
* **动作意图**: 缩小候选分子范围并准备后续打分。
* **依赖工件 (Inputs)**: artifact_constraints
* **挂载工具 (Required Tools)**: tool_run_sub_agent
* **预期产出 (Outputs)**: 候选分子列表

# 关键数据缺口
无`

    expect(parsePlanPreview(markdown)).toEqual({
      goal: '建立一条用于候选分子筛选的验证路径。',
      stages: [
        {
          id: 'stage-1',
          title: '收集靶点约束',
          intent: '汇总靶点约束并形成筛选边界。',
        },
        {
          id: 'stage-2',
          title: '筛选候选分子',
          intent: '缩小候选分子范围并准备后续打分。',
        },
      ],
    })
  })

  it('tolerates partially streamed markdown', () => {
    const markdown = `# 总体生化目标
建立快速验证流程。

# 执行管线 (Pipeline)
## 阶段 1：收集数据
* **动作意图**: 汇总现有结构与活性线索。`

    expect(parsePlanPreview(markdown)).toEqual({
      goal: '建立快速验证流程。',
      stages: [
        {
          id: 'stage-1',
          title: '收集数据',
          intent: '汇总现有结构与活性线索。',
        },
      ],
    })
  })
})
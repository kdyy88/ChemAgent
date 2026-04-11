import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const PLAN_MARKDOWN = `# 总体生化目标
设计一条面向候选抑制剂筛选的验证执行管线。

# 执行管线 (Pipeline)
## 阶段 1：收集靶点约束
* **动作意图**: 汇总已知靶点口袋和活性约束，为后续候选筛选建立边界。
* **依赖工件 (Inputs)**: 无
* **挂载工具 (Required Tools)**: database_lookup
* **预期产出 (Outputs)**: 靶点约束摘要

## 阶段 2：筛选候选分子
* **动作意图**: 基于约束快速缩小候选集，并保留可进入后续打分的分子。
* **依赖工件 (Inputs)**: artifact_target_constraints
* **挂载工具 (Required Tools)**: tool_run_sub_agent
* **预期产出 (Outputs)**: 候选分子列表

# 关键数据缺口
无`

const fetchPlanDocumentMock = vi.fn()
const approveToolCallMock = vi.fn()

vi.mock('@/lib/artifact-api', () => ({
  fetchPlanDocument: (...args: unknown[]) => fetchPlanDocumentMock(...args),
}))

vi.mock('@/services/sse-client', () => ({
  sseClient: { sessionId: 'session-1' },
}))

vi.mock('@/store/sseStore', () => ({
  useSseStore: () => ({
    approveToolCall: approveToolCallMock,
    isStreaming: false,
  }),
}))

import { ApprovalCard } from '../ApprovalCard'

describe('ApprovalCard', () => {
  beforeEach(() => {
    fetchPlanDocumentMock.mockReset()
    approveToolCallMock.mockReset()
  })

  it('loads plan content and submits modify with markdown content', async () => {
    fetchPlanDocumentMock.mockResolvedValue({
      plan_id: '1234567890abcdef1234567890abcdef',
      plan_file_ref: 'session-1/1234567890abcdef1234567890abcdef.md',
      status: 'pending_approval',
      summary: 'Plan summary',
      revision: 1,
      content: PLAN_MARKDOWN,
    })

    const user = userEvent.setup()
    render(
      <ApprovalCard
        approval={{
          kind: 'plan',
          plan_id: '1234567890abcdef1234567890abcdef',
          plan_file_ref: 'session-1/1234567890abcdef1234567890abcdef.md',
          summary: 'Plan summary',
          status: 'pending_approval',
          mode: 'plan',
          interrupt_id: 'interrupt-plan-1',
        }}
      />,
    )

    await waitFor(() => {
      expect(fetchPlanDocumentMock).toHaveBeenCalledWith('session-1', '1234567890abcdef1234567890abcdef')
    })

    await waitFor(() => {
      expect(screen.getByText('收集靶点约束')).toBeInTheDocument()
    })

    expect(screen.getByText('汇总已知靶点口袋和活性约束，为后续候选筛选建立边界。')).toBeInTheDocument()
    expect(screen.queryByText(/依赖工件/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Required Tools/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/关键数据缺口/i)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '编辑' }))

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    await user.clear(textarea)
    await user.type(textarea, '# Revised plan\n- Step A')
    await user.click(screen.getByRole('button', { name: '保存修改' }))

    await waitFor(() => {
      expect(approveToolCallMock).toHaveBeenCalledWith('modify', { content: '# Revised plan\n- Step A' })
    })
  })

  it('submits tool approval with parsed JSON args', async () => {
    const user = userEvent.setup()
    render(
      <ApprovalCard
        approval={{
          kind: 'tool',
          tool_name: 'tool_build_3d_conformer',
          args: { smiles: 'CCO' },
          tool_call_id: 'call-1',
          interrupt_id: 'interrupt-1',
        }}
      />,
    )

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    expect(textarea.value).toBe('{\n  "smiles": "CCO"\n}')
    fireEvent.change(textarea, { target: { value: '{"smiles":"CCN"}' } })
    await user.click(screen.getByRole('button', { name: '确认执行' }))

    await waitFor(() => {
      expect(approveToolCallMock).toHaveBeenCalledWith('approve', { smiles: 'CCN' })
    })
  })
})
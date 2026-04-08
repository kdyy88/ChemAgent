import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
      content: '# Initial plan\n- Step 1',
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
      expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('# Initial plan\n- Step 1')
    })

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
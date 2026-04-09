import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SSEEvent } from '@/lib/sse-types'

const { fetchEventSourceMock } = vi.hoisted(() => ({
  fetchEventSourceMock: vi.fn(),
}))

vi.mock('@microsoft/fetch-event-source', () => ({
  fetchEventSource: fetchEventSourceMock,
}))

import { useSseStore } from '../sseStore'
import { useWorkspaceStore } from '../workspaceStore'

describe('sseStore', () => {
  beforeEach(() => {
    fetchEventSourceMock.mockReset()
    // Reset state directly without calling clearTurns to avoid side effects in tests
    useSseStore.setState({
      turns: [],
      isStreaming: false,
    })
    useWorkspaceStore.setState({
      navMode: 'business',
      activeFunctionId: null,
      currentSmiles: '',
      currentName: '',
    })
  })

  afterEach(() => {
    useSseStore.getState().clearTurns()
  })

  it('tracks tool lifecycle and updates workspace from structured tool output', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: { onmessage?: (msg: { data: string }) => void }) => {
      const emit = (event: SSEEvent) => {
        options?.onmessage?.({ data: JSON.stringify(event) })
      }

      emit({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'Analyze aspirin' })
      emit({ type: 'tool_start', tool: 'tool_validate_smiles', input: { smiles: 'CCO' }, session_id: 'session-1', turn_id: 'turn-1' })
      emit({
        type: 'tool_end',
        tool: 'tool_validate_smiles',
        output: { canonical_smiles: 'OCC', name: 'Ethanol', is_valid: true },
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({ type: 'done', session_id: 'session-1', turn_id: 'turn-1' })
    })

    await useSseStore.getState().sendMessage('Analyze aspirin')

    const turn = useSseStore.getState().turns[0]
    expect(turn.toolCalls).toHaveLength(1)
    expect(turn.toolCalls[0]).toMatchObject({
      tool: 'tool_validate_smiles',
      done: true,
      output: { canonical_smiles: 'OCC', name: 'Ethanol', is_valid: true },
    })
    expect(useWorkspaceStore.getState().currentSmiles).toBe('OCC')
    expect(useWorkspaceStore.getState().currentName).toBe('Ethanol')
    expect(useSseStore.getState().isStreaming).toBe(false)
  })

  it('resolves the latest unfinished tool call of the same name without reverse scanning assumptions', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: { onmessage?: (msg: { data: string }) => void }) => {
      const emit = (event: SSEEvent) => {
        options?.onmessage?.({ data: JSON.stringify(event) })
      }

      emit({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'multi tool' })
      emit({ type: 'tool_start', tool: 'tool_convert_format', input: { value: 1 }, session_id: 'session-1', turn_id: 'turn-1' })
      emit({ type: 'tool_start', tool: 'tool_convert_format', input: { value: 2 }, session_id: 'session-1', turn_id: 'turn-1' })
      emit({
        type: 'tool_end',
        tool: 'tool_convert_format',
        output: { output_format: 'mol2', output: 'second' },
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({
        type: 'tool_end',
        tool: 'tool_convert_format',
        output: { output_format: 'sdf', output: 'first' },
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({ type: 'done', session_id: 'session-1', turn_id: 'turn-1' })
    })

    await useSseStore.getState().sendMessage('multi tool')

    const [firstCall, secondCall] = useSseStore.getState().turns[0].toolCalls
    expect(firstCall.output).toEqual({ output_format: 'sdf', output: 'first' })
    expect(secondCall.output).toEqual({ output_format: 'mol2', output: 'second' })
  })

  it('stores latest PubChem result for interrupt resume context', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: { onmessage?: (msg: { data: string }) => void }) => {
      const emit = (event: SSEEvent) => {
        options?.onmessage?.({ data: JSON.stringify(event) })
      }

      emit({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'lookup' })
      emit({ type: 'tool_start', tool: 'tool_pubchem_lookup', input: { name: 'aspirin' }, session_id: 'session-1', turn_id: 'turn-1' })
      emit({
        type: 'tool_end',
        tool: 'tool_pubchem_lookup',
        output: { canonical_smiles: 'CC(=O)OC1=CC=CC=C1C(=O)O', found: true },
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({
        type: 'interrupt',
        question: '请确认化合物名称',
        options: ['阿司匹林', '水杨酸'],
        called_tools: ['tool_pubchem_lookup'],
        interrupt_id: 'interrupt-1',
        known_smiles: 'CC(=O)OC1=CC=CC=C1C(=O)O',
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
    })

    await useSseStore.getState().sendMessage('lookup')

    const turn = useSseStore.getState().turns[0]
    expect(turn.pendingInterrupt).toMatchObject({
      question: '请确认化合物名称',
      known_smiles: 'CC(=O)OC1=CC=CC=C1C(=O)O',
    })
    expect(useSseStore.getState().isStreaming).toBe(false)
  })

  it('stores plan approval requests as pending plan approvals', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: { onmessage?: (msg: { data: string }) => void }) => {
      const emit = (event: SSEEvent) => {
        options?.onmessage?.({ data: JSON.stringify(event) })
      }

      emit({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'draft a plan' })
      emit({
        type: 'plan_approval_request',
        plan_id: '1234567890abcdef1234567890abcdef',
        plan_file_ref: 'session-1/1234567890abcdef1234567890abcdef.md',
        summary: 'Three-step synthesis and validation plan',
        status: 'pending_approval',
        mode: 'plan',
        interrupt_id: 'interrupt-plan-1',
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
    })

    await useSseStore.getState().sendMessage('draft a plan')

    const turn = useSseStore.getState().turns[0]
    expect(turn.pendingApproval).toMatchObject({
      kind: 'plan',
      plan_id: '1234567890abcdef1234567890abcdef',
      summary: 'Three-step synthesis and validation plan',
      status: 'pending_approval',
    })
    expect(useSseStore.getState().isStreaming).toBe(false)
  })

  it('tracks planner task updates for the active turn', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: { onmessage?: (msg: { data: string }) => void }) => {
      const emit = (event: SSEEvent) => {
        options?.onmessage?.({ data: JSON.stringify(event) })
      }

      emit({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'complex job' })
      emit({ type: 'node_start', node: 'planner_node', session_id: 'session-1', turn_id: 'turn-1' })
      emit({
        type: 'task_update',
        tasks: [
          { id: '1', description: '联网搜索 KRAS 抑制剂', status: 'completed' },
          { id: '2', description: '提取候选分子骨架', status: 'in_progress' },
          { id: '3', description: '计算骨架的 Lipinski 规则', status: 'pending' },
        ],
        source: 'planner_node',
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({ type: 'done', session_id: 'session-1', turn_id: 'turn-1' })
    })

    await useSseStore.getState().sendMessage('complex job')

    const turn = useSseStore.getState().turns[0]
    expect(turn.tasks).toHaveLength(3)
    expect(turn.tasks[1]).toMatchObject({
      id: '2',
      status: 'in_progress',
    })
    expect(turn.statusLabel).toBe('')
  })

  it('filters low-value thinking logs while keeping meaningful tool actions', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: { onmessage?: (msg: { data: string }) => void }) => {
      const emit = (event: SSEEvent) => {
        options?.onmessage?.({ data: JSON.stringify(event) })
      }

      emit({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'optimize' })
      emit({
        type: 'thinking',
        text: '准备转入工具执行流水线...',
        iteration: 0,
        done: true,
        source: 'tools_executor',
        category: 'node',
        importance: 'low',
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({
        type: 'thinking',
        text: '正在调用：生成三维构象',
        iteration: 0,
        done: true,
        source: 'tools_executor',
        category: 'tool',
        importance: 'high',
        group_key: 'tool_build_3d_conformer',
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({ type: 'done', session_id: 'session-1', turn_id: 'turn-1' })
    })

    await useSseStore.getState().sendMessage('optimize')

    const turn = useSseStore.getState().turns[0]
    expect(turn.thinkingSteps).toHaveLength(1)
    expect(turn.thinkingSteps[0].text).toBe('正在调用：生成三维构象')
  })

  it('routes sub-agent token streams into thinking and preserves parent stream updates', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: { onmessage?: (msg: { data: string }) => void }) => {
      const emit = (event: SSEEvent) => {
        options?.onmessage?.({ data: JSON.stringify(event) })
      }

      emit({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'research' })
      emit({ type: 'tool_start', tool: 'tool_run_sub_agent', input: { mode: 'explore' }, session_id: 'session-1', turn_id: 'turn-1' })
      emit({
        type: 'thinking',
        text: '正在调用：run_sub_agent',
        iteration: 0,
        done: true,
        source: 'tools_executor',
        category: 'tool',
        importance: 'high',
        group_key: 'tool_run_sub_agent',
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({
        type: 'token',
        node: 'sub_agent[explore]',
        source: 'sub_agent',
        content: 'Analyzing scaffold similarities...',
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({
        type: 'task_update',
        tasks: [
          { id: '1', description: '调研候选骨架', status: 'completed' },
          { id: '2', description: '汇总设计约束', status: 'in_progress' },
        ],
        source: 'tools_executor',
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({ type: 'tool_end', tool: 'tool_run_sub_agent', output: { status: 'ok' }, session_id: 'session-1', turn_id: 'turn-1' })
      emit({
        type: 'token',
        node: 'chem_agent',
        content: 'Parent agent continues with the integrated result.',
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({ type: 'done', session_id: 'session-1', turn_id: 'turn-1' })
    })

    await useSseStore.getState().sendMessage('research')

    const turn = useSseStore.getState().turns[0]
    expect(turn.assistantText).toBe('Parent agent continues with the integrated result.')
    expect(turn.thinkingSteps).toHaveLength(3)
    expect(turn.thinkingSteps[0].text).toBe('正在调用：run_sub_agent')
    expect(turn.thinkingSteps[1].text).toBe('Analyzing scaffold similarities...')
    expect(turn.thinkingSteps[2].text).toBe('子智能体任务完成，结果已返回主流程。')
    expect(turn.tasks[1]).toMatchObject({ id: '2', status: 'in_progress' })
  })

  it('ignores silent task-status tools in the client tool timeline', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: { onmessage?: (msg: { data: string }) => void }) => {
      const emit = (event: SSEEvent) => {
        options?.onmessage?.({ data: JSON.stringify(event) })
      }

      emit({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'silent tool' })
      emit({ type: 'tool_start', tool: 'tool_update_task_status', input: { task_id: '1' }, session_id: 'session-1', turn_id: 'turn-1' })
      emit({
        type: 'tool_end',
        tool: 'tool_update_task_status',
        output: { task_id: '1', task_status: 'completed' },
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({ type: 'done', session_id: 'session-1', turn_id: 'turn-1' })
    })

    await useSseStore.getState().sendMessage('silent tool')

    expect(useSseStore.getState().turns[0].toolCalls).toHaveLength(0)
  })

  it('treats a clean close after done as successful completion', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: {
      onmessage?: (msg: { data: string }) => void
      onclose?: () => void
    }) => {
      const emit = (event: SSEEvent) => {
        options?.onmessage?.({ data: JSON.stringify(event) })
      }

      emit({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'done close' })
      emit({ type: 'done', session_id: 'session-1', turn_id: 'turn-1' })
      options?.onclose?.()
    })

    await expect(useSseStore.getState().sendMessage('done close')).resolves.toBeUndefined()
    expect(useSseStore.getState().isStreaming).toBe(false)
  })

  it('surfaces premature stream closure instead of silently allowing a retry', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: {
      onmessage?: (msg: { data: string }) => void
      onclose?: () => void
    }) => {
      options?.onmessage?.({
        data: JSON.stringify({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'premature close' } satisfies SSEEvent),
      })
      options?.onclose?.()
    })

    await expect(useSseStore.getState().sendMessage('premature close')).rejects.toThrow(
      'SSE stream closed before a terminal event was received',
    )
  })

  it('clears workspace state (currentSmiles and currentName) when clearTurns is called', async () => {
    fetchEventSourceMock.mockImplementation(async (_url: string, options?: { onmessage?: (msg: { data: string }) => void }) => {
      const emit = (event: SSEEvent) => {
        options?.onmessage?.({ data: JSON.stringify(event) })
      }

      emit({ type: 'run_started', session_id: 'session-1', turn_id: 'turn-1', message: 'test molecule' })
      emit({ type: 'tool_start', tool: 'tool_validate_smiles', input: { smiles: 'CCO' }, session_id: 'session-1', turn_id: 'turn-1' })
      emit({
        type: 'tool_end',
        tool: 'tool_validate_smiles',
        output: { canonical_smiles: 'CCO', name: 'Ethanol', is_valid: true },
        session_id: 'session-1',
        turn_id: 'turn-1',
      })
      emit({ type: 'done', session_id: 'session-1', turn_id: 'turn-1' })
    })

    await useSseStore.getState().sendMessage('test molecule')

    expect(useWorkspaceStore.getState().currentSmiles).toBe('CCO')
    expect(useWorkspaceStore.getState().currentName).toBe('Ethanol')
    expect(useSseStore.getState().turns).toHaveLength(1)

    useSseStore.getState().clearTurns()

    expect(useSseStore.getState().turns).toHaveLength(0)
    expect(useWorkspaceStore.getState().currentSmiles).toBe('')
    expect(useWorkspaceStore.getState().currentName).toBe('')
  })
})

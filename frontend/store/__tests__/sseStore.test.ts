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
    useSseStore.getState().clearTurns()
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
})

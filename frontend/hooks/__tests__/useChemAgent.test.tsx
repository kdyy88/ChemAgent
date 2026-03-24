import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

// Mock the entire chatStore before importing useChemAgent
const mockInitialize = vi.fn()
const mockSetAgentModels = vi.fn()
const mockSendMessage = vi.fn()
const mockClearTurns = vi.fn()

const mockState = {
  turns: [{ id: 'turn-1' }],
  isStreaming: true,
  toolCatalog: { validate_smiles: { name: 'validate_smiles', description: '', displayName: 'Validate', category: 'rdkit', outputKinds: [], tags: [] } },
  agentModels: { manager: 'gpt-4o' },
  setAgentModels: mockSetAgentModels,
  sendMessage: mockSendMessage,
  clearTurns: mockClearTurns,
  initialize: mockInitialize,
}

vi.mock('@/store/chatStore', () => ({
  // useChatStore is called with a selector function: useChatStore((s) => s.turns)
  useChatStore: vi.fn((selector: (s: typeof mockState) => unknown) => selector(mockState)),
}))

// Import AFTER mock is set up
import { useChemAgent } from '../useChemAgent'

beforeEach(() => {
  mockInitialize.mockClear()
  mockSetAgentModels.mockClear()
  mockSendMessage.mockClear()
  mockClearTurns.mockClear()
})

describe('useChemAgent()', () => {
  it('calls initialize() exactly once on mount', () => {
    renderHook(() => useChemAgent())
    expect(mockInitialize).toHaveBeenCalledOnce()
  })

  it('does not call initialize() again on re-render', () => {
    const { rerender } = renderHook(() => useChemAgent())
    rerender()
    rerender()
    expect(mockInitialize).toHaveBeenCalledOnce()
  })

  it('returns turns from the store', () => {
    const { result } = renderHook(() => useChemAgent())
    expect(result.current.turns).toEqual(mockState.turns)
  })

  it('returns isStreaming from the store', () => {
    const { result } = renderHook(() => useChemAgent())
    expect(result.current.isStreaming).toBe(true)
  })

  it('returns toolCatalog from the store', () => {
    const { result } = renderHook(() => useChemAgent())
    expect(result.current.toolCatalog).toEqual(mockState.toolCatalog)
  })

  it('returns agentModels from the store', () => {
    const { result } = renderHook(() => useChemAgent())
    expect(result.current.agentModels).toEqual({ manager: 'gpt-4o' })
  })

  it('returns setAgentModels function', () => {
    const { result } = renderHook(() => useChemAgent())
    expect(result.current.setAgentModels).toBe(mockSetAgentModels)
  })

  it('returns sendMessage function', () => {
    const { result } = renderHook(() => useChemAgent())
    expect(result.current.sendMessage).toBe(mockSendMessage)
  })

  it('returns clearTurns function', () => {
    const { result } = renderHook(() => useChemAgent())
    expect(result.current.clearTurns).toBe(mockClearTurns)
  })
})

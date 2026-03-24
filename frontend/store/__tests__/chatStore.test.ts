import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useChatStore } from '../chatStore'

// ── Mocks ──────────────────────────────────────────────────────────────────────

const mockPersistSessionId = vi.fn()
const mockSend = vi.fn()

vi.mock('@/lib/chat/session', () => ({
  loadStoredSessionId: vi.fn().mockReturnValue(null),
  persistSessionId: (...args: unknown[]) => mockPersistSessionId(...args),
}))

vi.mock('@/lib/chat/socket', () => ({
  connectChatSocket: vi.fn(() => ({
    readyState: 1, // WebSocket.OPEN
    send: (...args: unknown[]) => mockSend(...args),
  })),
}))

// Provide WebSocket static constants referenced in the store
beforeEach(() => {
  mockPersistSessionId.mockClear()
  mockSend.mockClear()

  vi.stubGlobal('WebSocket', Object.assign(vi.fn(), { OPEN: 1, CONNECTING: 0 }))

  // Reset store to a clean state between tests
  useChatStore.setState({
    sessionId: null,
    turns: [],
    isStreaming: false,
    wsRef: null,
    toolCatalog: {},
    pendingTurn: null,
    reconnectTimer: null,
    reconnectAttempts: 0,
    agentModels: {},
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ── setAgentModels ─────────────────────────────────────────────────────────────

describe('chatStore – setAgentModels()', () => {
  it('updates agentModels in the store', () => {
    const config = { manager: 'gpt-4o', visualizer: 'gpt-4o-mini' }
    useChatStore.getState().setAgentModels(config)
    expect(useChatStore.getState().agentModels).toEqual(config)
  })

  it('writes the config to localStorage', () => {
    const config = { manager: 'gpt-5-mini' }
    useChatStore.getState().setAgentModels(config)
    const stored = JSON.parse(localStorage.getItem('chemagent_model_prefs') ?? '{}')
    expect(stored).toEqual(config)
  })

  it('replaces the previous config fully', () => {
    useChatStore.getState().setAgentModels({ manager: 'gpt-4o' })
    useChatStore.getState().setAgentModels({ manager: 'gpt-5-nano', researcher: 'gpt-4o-mini' })
    expect(useChatStore.getState().agentModels).toEqual({ manager: 'gpt-5-nano', researcher: 'gpt-4o-mini' })
  })
})

// ── sendMessage ────────────────────────────────────────────────────────────────

describe('chatStore – sendMessage()', () => {
  it('is a no-op for empty string', () => {
    useChatStore.getState().sendMessage('')
    expect(useChatStore.getState().turns).toHaveLength(0)
    expect(useChatStore.getState().isStreaming).toBe(false)
  })

  it('is a no-op for whitespace-only string', () => {
    useChatStore.getState().sendMessage('   ')
    expect(useChatStore.getState().turns).toHaveLength(0)
  })

  it('is a no-op when isStreaming is true', () => {
    useChatStore.setState({ isStreaming: true })
    useChatStore.getState().sendMessage('Hello')
    expect(useChatStore.getState().turns).toHaveLength(0)
  })

  it('adds a new turn with the trimmed prompt', () => {
    useChatStore.getState().sendMessage('  What is aspirin?  ')
    expect(useChatStore.getState().turns).toHaveLength(1)
    expect(useChatStore.getState().turns[0].userMessage).toBe('What is aspirin?')
  })

  it('sets isStreaming to true', () => {
    useChatStore.getState().sendMessage('CCO')
    expect(useChatStore.getState().isStreaming).toBe(true)
  })

  it('new turn has status "thinking"', () => {
    useChatStore.getState().sendMessage('test')
    expect(useChatStore.getState().turns[0].status).toBe('thinking')
  })

  it('new turn has empty steps and artifacts', () => {
    useChatStore.getState().sendMessage('test')
    const turn = useChatStore.getState().turns[0]
    expect(turn.steps).toEqual([])
    expect(turn.artifacts).toEqual([])
  })

  it('appends additional turns without removing existing ones', () => {
    useChatStore.getState().sendMessage('First')
    useChatStore.setState({ isStreaming: false })
    useChatStore.getState().sendMessage('Second')
    expect(useChatStore.getState().turns).toHaveLength(2)
  })
})

// ── clearTurns ────────────────────────────────────────────────────────────────

describe('chatStore – clearTurns()', () => {
  it('empties the turns array', () => {
    useChatStore.getState().sendMessage('Hello')
    useChatStore.setState({ isStreaming: false })
    useChatStore.getState().clearTurns()
    expect(useChatStore.getState().turns).toHaveLength(0)
  })

  it('resets sessionId to null', () => {
    useChatStore.setState({ sessionId: 'some-session' })
    useChatStore.getState().clearTurns()
    expect(useChatStore.getState().sessionId).toBeNull()
  })

  it('resets pendingTurn to null', () => {
    useChatStore.setState({ pendingTurn: { turnId: 'x', prompt: 'y' } })
    useChatStore.getState().clearTurns()
    expect(useChatStore.getState().pendingTurn).toBeNull()
  })

  it('calls persistSessionId(null)', () => {
    useChatStore.getState().clearTurns()
    expect(mockPersistSessionId).toHaveBeenCalledWith(null)
  })

  it('sends session.clear when WebSocket is open', () => {
    const mockWs = { readyState: 1, send: vi.fn() }
    useChatStore.setState({ wsRef: mockWs as unknown as WebSocket })

    useChatStore.getState().clearTurns()

    expect(mockWs.send).toHaveBeenCalledOnce()
    const msg = JSON.parse(mockWs.send.mock.calls[0][0] as string)
    expect(msg.type).toBe('session.clear')
  })

  it('does not call ws.send when wsRef is null', () => {
    useChatStore.setState({ wsRef: null })
    expect(() => useChatStore.getState().clearTurns()).not.toThrow()
    expect(mockSend).not.toHaveBeenCalled()
  })
})

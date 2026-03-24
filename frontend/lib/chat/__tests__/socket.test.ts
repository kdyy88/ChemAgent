import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { connectChatSocket } from '../socket'

// ── Mock WebSocket ─────────────────────────────────────────────────────────────

class MockWebSocket {
  static OPEN = 1
  static CONNECTING = 0
  static CLOSING = 2
  static CLOSED = 3

  url: string
  readyState = MockWebSocket.OPEN
  sent: string[] = []

  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null

  constructor(url: string) {
    this.url = url
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {}

  // Helpers to simulate server-side events in tests
  triggerOpen() {
    this.onopen?.()
  }
  triggerMessage(data: string) {
    this.onmessage?.({ data })
  }
  triggerError() {
    this.onerror?.(new Event('error'))
  }
  triggerClose() {
    this.onclose?.(new CloseEvent('close'))
  }
}

let mockWs: MockWebSocket

beforeEach(() => {
  mockWs = null as unknown as MockWebSocket
  vi.stubGlobal('WebSocket', class extends MockWebSocket {
    constructor(url: string) {
      super(url)
      mockWs = this
    }
  })
  // Make WebSocket.OPEN accessible under the global
  Object.assign(global.WebSocket, { OPEN: 1, CONNECTING: 0 })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function makeCallbacks() {
  return {
    getSessionId: vi.fn<() => string | null>().mockReturnValue(null),
    getAgentModels: vi.fn().mockReturnValue({ manager: 'gpt-4o-mini' }),
    onEvent: vi.fn(),
    onClosed: vi.fn(),
  }
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('connectChatSocket()', () => {
  it('creates a WebSocket and returns it', () => {
    const ws = connectChatSocket(makeCallbacks())
    expect(ws).toBeDefined()
  })

  it('sends session.start when getSessionId returns null', () => {
    const cbs = makeCallbacks()
    cbs.getSessionId.mockReturnValue(null)
    connectChatSocket(cbs)
    mockWs.triggerOpen()

    expect(mockWs.sent).toHaveLength(1)
    const msg = JSON.parse(mockWs.sent[0])
    expect(msg.type).toBe('session.start')
    expect(msg.agent_models).toEqual({ manager: 'gpt-4o-mini' })
  })

  it('sends session.resume when getSessionId returns a session id', () => {
    const cbs = makeCallbacks()
    cbs.getSessionId.mockReturnValue('sess-abc')
    connectChatSocket(cbs)
    mockWs.triggerOpen()

    expect(mockWs.sent).toHaveLength(1)
    const msg = JSON.parse(mockWs.sent[0])
    expect(msg.type).toBe('session.resume')
    expect(msg.session_id).toBe('sess-abc')
  })

  it('responds to ping with pong and does NOT call onEvent', () => {
    const cbs = makeCallbacks()
    connectChatSocket(cbs)
    mockWs.triggerOpen()
    mockWs.sent = [] // clear the session.start message

    mockWs.triggerMessage(JSON.stringify({ type: 'ping' }))

    expect(mockWs.sent).toHaveLength(1)
    expect(JSON.parse(mockWs.sent[0]).type).toBe('pong')
    expect(cbs.onEvent).not.toHaveBeenCalled()
  })

  it('calls onEvent with parsed message for non-ping messages', () => {
    const cbs = makeCallbacks()
    connectChatSocket(cbs)

    const payload = { type: 'session.started', session_id: 'x', tools: [], resumed: false }
    mockWs.triggerMessage(JSON.stringify(payload))

    expect(cbs.onEvent).toHaveBeenCalledWith(payload)
  })

  it('silently swallows malformed JSON', () => {
    const cbs = makeCallbacks()
    connectChatSocket(cbs)

    expect(() => mockWs.triggerMessage('NOT_JSON{{')).not.toThrow()
    expect(cbs.onEvent).not.toHaveBeenCalled()
  })

  it('calls onClosed on WebSocket error', () => {
    const cbs = makeCallbacks()
    connectChatSocket(cbs)
    mockWs.triggerError()

    expect(cbs.onClosed).toHaveBeenCalledOnce()
  })

  it('calls onClosed on WebSocket close', () => {
    const cbs = makeCallbacks()
    connectChatSocket(cbs)
    mockWs.triggerClose()

    expect(cbs.onClosed).toHaveBeenCalledOnce()
  })

  it('does not send pong when ws is not OPEN', () => {
    const cbs = makeCallbacks()
    connectChatSocket(cbs)
    mockWs.sent = []
    mockWs.readyState = MockWebSocket.CLOSED

    mockWs.triggerMessage(JSON.stringify({ type: 'ping' }))

    expect(mockWs.sent).toHaveLength(0)
  })
})

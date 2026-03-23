import type { AgentModelConfig, ClientEvent, ServerEvent } from '@/lib/types'

function normalizeWebSocketBaseUrl(url: string): string {
  return url.replace('ws://localhost:', 'ws://127.0.0.1:').replace('wss://localhost:', 'wss://127.0.0.1:')
}

function resolveWebSocketUrl(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL?.trim()
  if (configured) {
    const normalized = normalizeWebSocketBaseUrl(configured.replace(/\/$/, ''))
    return normalized.endsWith('/api/chat/ws') ? normalized : `${normalized}/api/chat/ws`
  }

  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.hostname === 'localhost'
      ? `127.0.0.1${window.location.port ? `:${window.location.port}` : ''}`
      : window.location.host
    return `${protocol}//${host}/api/chat/ws`
  }

  return 'ws://127.0.0.1:3030/api/chat/ws'
}

type SocketCallbacks = {
  getSessionId: () => string | null
  getAgentModels: () => AgentModelConfig
  onEvent: (event: ServerEvent) => void
  onClosed: () => void
}

export function connectChatSocket({ getSessionId, getAgentModels, onEvent, onClosed }: SocketCallbacks): WebSocket {
  const ws = new WebSocket(resolveWebSocketUrl())

  ws.onopen = () => {
    const sessionId = getSessionId()
    const message: ClientEvent = sessionId
      ? { type: 'session.resume', session_id: sessionId }
      : { type: 'session.start', agent_models: getAgentModels() }
    ws.send(JSON.stringify(message))
  }

  ws.onmessage = (event: MessageEvent) => {
    try {
      onEvent(JSON.parse(event.data as string) as ServerEvent)
    } catch {
      // Ignore malformed frames.
    }
  }

  ws.onerror = () => onClosed()
  ws.onclose = () => onClosed()

  return ws
}

import type { ClientEvent, ServerEvent } from '@/lib/types'

function resolveWebSocketUrl(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL?.trim()
  if (configured) {
    const normalized = configured.replace(/\/$/, '')
    return normalized.endsWith('/api/chat/ws') ? normalized : `${normalized}/api/chat/ws`
  }

  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}/api/chat/ws`
  }

  return 'ws://127.0.0.1:3030/api/chat/ws'
}

type SocketCallbacks = {
  getSessionId: () => string | null
  onEvent: (event: ServerEvent) => void
  onClosed: () => void
}

export function connectChatSocket({ getSessionId, onEvent, onClosed }: SocketCallbacks): WebSocket {
  const ws = new WebSocket(resolveWebSocketUrl())

  ws.onopen = () => {
    const sessionId = getSessionId()
    const message: ClientEvent = sessionId
      ? { type: 'session.resume', session_id: sessionId }
      : { type: 'session.start' }
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

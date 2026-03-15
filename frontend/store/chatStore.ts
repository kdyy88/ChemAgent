import { create } from 'zustand'
import type { ClientEvent, ToolMeta, Turn } from '@/lib/types'
import { connectChatSocket } from '@/lib/chat/socket'
import { applyServerEvent, applySocketClosed, createTurn, type ChatStateSlice, type PendingTurn } from '@/lib/chat/state'

interface ChatStore extends ChatStateSlice {
  wsRef: WebSocket | null
  pendingTurn: PendingTurn | null
  sendMessage: (prompt: string) => void
  clearTurns: () => void
}

const flushPendingTurn = (get: () => ChatStore): boolean => {
  const state = get()
  if (!state.pendingTurn || !state.wsRef || state.wsRef.readyState !== WebSocket.OPEN || !state.sessionId) {
    return false
  }

  const message: ClientEvent = {
    type: 'user.message',
    turn_id: state.pendingTurn.turnId,
    content: state.pendingTurn.prompt,
  }
  state.wsRef.send(JSON.stringify(message))
  return true
}

const connectSocket = (
  set: (updater: Partial<ChatStore> | ((state: ChatStore) => Partial<ChatStore>)) => void,
  get: () => ChatStore,
) => {
  const existing = get().wsRef
  if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
    return
  }

  const ws = connectChatSocket({
    getSessionId: () => get().sessionId,
    onEvent: (msg) => {
      set((state) => {
        const nextState = applyServerEvent(state, msg)
        if (msg.type === 'session.started') {
          return nextState
        }
        return nextState
      })

      if (msg.type === 'session.started') {
        if (flushPendingTurn(get)) {
          set({ pendingTurn: null })
        }
      }
    },
    onClosed: () => {
      set((state) => ({
        ...applySocketClosed(state.turns),
        wsRef: null,
      }))
    },
  })
  set({ wsRef: ws })
}

export const useChatStore = create<ChatStore>((set, get) => ({
  sessionId: null,
  turns: [],
  isStreaming: false,
  wsRef: null,
  toolCatalog: {} as Record<string, ToolMeta>,
  pendingTurn: null,

  sendMessage: (prompt: string) => {
    if (get().isStreaming) return

    const trimmed = prompt.trim()
    if (!trimmed) return

    const newTurn: Turn = createTurn(trimmed)

    set((state) => ({
      turns: [...state.turns, newTurn],
      isStreaming: true,
      sessionId: state.sessionId,
      pendingTurn: { turnId: newTurn.id, prompt: trimmed },
    }))

    connectSocket(set, get)
    if (flushPendingTurn(get)) {
      set({ pendingTurn: null })
    }
  },

  clearTurns: () => {
    const ws = get().wsRef
    if (ws && ws.readyState === WebSocket.OPEN) {
      const message: ClientEvent = { type: 'session.clear', content: '' }
      ws.send(JSON.stringify(message))
    }

    set({ turns: [], sessionId: null, pendingTurn: null })
  },
}))

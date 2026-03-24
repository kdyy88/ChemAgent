import { create } from 'zustand'
import type { AgentModelConfig, ClientEvent, ToolMeta, Turn } from '@/lib/types'
import { connectChatSocket } from '@/lib/chat/socket'
import { loadStoredSessionId, persistSessionId } from '@/lib/chat/session'
import { applyServerEvent, applySocketClosed, createTurn, type ChatStateSlice, type PendingTurn } from '@/lib/chat/state'

const STORAGE_KEY = 'chemagent_model_prefs'

function loadStoredModels(): AgentModelConfig {
  if (typeof window === 'undefined') return {}
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AgentModelConfig) : {}
  } catch {
    return {}
  }
}

function saveStoredModels(config: AgentModelConfig): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  } catch {
    // Quota exceeded or private browsing — silently ignore.
  }
}

interface ChatStore extends ChatStateSlice {
  wsRef: WebSocket | null
  pendingTurn: PendingTurn | null
  reconnectTimer: number | null
  reconnectAttempts: number
  initialize: () => void
  setAgentModels: (config: AgentModelConfig) => void
  sendMessage: (prompt: string) => void
  clearTurns: () => void
}

function clearReconnectTimer(timer: number | null): void {
  if (timer !== null && typeof window !== 'undefined') {
    window.clearTimeout(timer)
  }
}

function scheduleReconnect(
  set: (updater: Partial<ChatStore> | ((state: ChatStore) => Partial<ChatStore>)) => void,
  get: () => ChatStore,
): void {
  if (typeof window === 'undefined') return

  const state = get()
  if (state.reconnectTimer !== null) return

  const delay = Math.min(1000 * 2 ** state.reconnectAttempts, 10000)
  const timer = window.setTimeout(() => {
    set((current) => ({
      reconnectTimer: null,
      reconnectAttempts: current.reconnectAttempts + 1,
    }))
    connectSocket(set, get)
  }, delay)

  set({ reconnectTimer: timer })
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
    getAgentModels: () => get().agentModels,
    onEvent: (msg) => {
      set((state) => applyServerEvent(state, msg))

      if (msg.type === 'session.started') {
        persistSessionId(msg.session_id)
        set({ reconnectAttempts: 0 })
        // If a greeting is about to stream, defer flushing any pending turn
        // until the greeting finishes — otherwise the user's queued message
        // races with the greeting turn and both appear simultaneously.
        if (!msg.has_greeting) {
          if (flushPendingTurn(get)) {
            set({ pendingTurn: null })
          }
        }
      }

      // After any run finishes (including the greeting), flush a queued pending
      // turn so a message the user sent while connecting isn't lost.
      if (msg.type === 'run.finished' || msg.type === 'run.failed') {
        if (flushPendingTurn(get)) {
          set({ pendingTurn: null, isStreaming: true })
        }
      }

      // Keep localStorage in sync when the backend echoes back the real model
      // bindings so the next new session pre-selects the same combination.
      if (msg.type === 'session.started' && msg.agent_models) {
        saveStoredModels(msg.agent_models)
      }
    },
    onClosed: () => {
      set((state) => ({
        ...applySocketClosed(state.turns),
        wsRef: null,
      }))
      scheduleReconnect(set, get)
    },
  })
  clearReconnectTimer(get().reconnectTimer)
  set({ wsRef: ws, reconnectTimer: null })
}

export const useChatStore = create<ChatStore>((set, get) => ({
  sessionId: loadStoredSessionId(),
  turns: [],
  isStreaming: false,
  wsRef: null,
  toolCatalog: {} as Record<string, ToolMeta>,
  pendingTurn: null,
  reconnectTimer: null,
  reconnectAttempts: 0,
  agentModels: loadStoredModels(),

  // Connect the WebSocket eagerly (called on page mount) so the greeting
  // pre-warms before the user types anything.
  initialize: () => {
    connectSocket(set, get)
  },

  setAgentModels: (config: AgentModelConfig) => {
    set({ agentModels: config })
    saveStoredModels(config)
  },

  sendMessage: (prompt: string) => {
    if (get().isStreaming) return

    const trimmed = prompt.trim()
    if (!trimmed) return

    const newTurn: Turn = createTurn(trimmed)

    set((state) => ({
      turns: [...state.turns, newTurn],
      isStreaming: true,
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
      const message: ClientEvent = {
        type: 'session.clear',
        content: '',
        agent_models: get().agentModels,
      }
      ws.send(JSON.stringify(message))
    }

    persistSessionId(null)
    set({ turns: [], sessionId: null, pendingTurn: null })
  },
}))

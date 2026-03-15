import { useEffect } from 'react'
import { useChatStore } from '@/store/chatStore'
import type { AgentModelConfig, ToolMeta, Turn } from '@/lib/types'

/**
 * useChemAgent — the canonical public hook for all components.
 *
 * Wraps the Zustand store so components never import the store directly.
 * Returns only what components need; internal WebSocket plumbing is hidden.
 *
 * Eagerly connects the WebSocket on first mount so the backend greeting
 * pre-warms before the user types anything.
 */
export function useChemAgent(): {
  turns: Turn[]
  isStreaming: boolean
  toolCatalog: Record<string, ToolMeta>
  agentModels: AgentModelConfig
  setAgentModels: (config: AgentModelConfig) => void
  sendMessage: (prompt: string) => void
  clearTurns: () => void
} {
  const turns = useChatStore((s) => s.turns)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const toolCatalog = useChatStore((s) => s.toolCatalog)
  const agentModels = useChatStore((s) => s.agentModels)
  const setAgentModels = useChatStore((s) => s.setAgentModels)
  const sendMessage = useChatStore((s) => s.sendMessage)
  const clearTurns = useChatStore((s) => s.clearTurns)
  const initialize = useChatStore((s) => s.initialize)

  // Connect once on mount — idempotent, safe to call multiple times.
  useEffect(() => {
    initialize()
  }, [initialize])

  return { turns, isStreaming, toolCatalog, agentModels, setAgentModels, sendMessage, clearTurns }
}

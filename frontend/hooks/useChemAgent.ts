import { useEffect } from 'react'
import { useChatStore } from '@/store/chatStore'
import type { ConnectionStatus } from '@/store/chatStore'
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
  connectionStatus: ConnectionStatus
  toolCatalog: Record<string, ToolMeta>
  agentModels: AgentModelConfig
  autoApprove: boolean
  setAgentModels: (config: AgentModelConfig) => void
  sendMessage: (prompt: string) => void
  clearTurns: () => void
  approvePlan: (feedback?: string) => void
  rejectPlan: () => void
  setAutoApprove: (enabled: boolean) => void
} {
  const turns = useChatStore((s) => s.turns)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const connectionStatus = useChatStore((s) => s.connectionStatus)
  const toolCatalog = useChatStore((s) => s.toolCatalog)
  const agentModels = useChatStore((s) => s.agentModels)
  const autoApprove = useChatStore((s) => s.autoApprove)
  const setAgentModels = useChatStore((s) => s.setAgentModels)
  const sendMessage = useChatStore((s) => s.sendMessage)
  const clearTurns = useChatStore((s) => s.clearTurns)
  const approvePlan = useChatStore((s) => s.approvePlan)
  const rejectPlan = useChatStore((s) => s.rejectPlan)
  const setAutoApprove = useChatStore((s) => s.setAutoApprove)
  const initialize = useChatStore((s) => s.initialize)

  // Connect once on mount — idempotent, safe to call multiple times.
  useEffect(() => {
    initialize()
  }, [initialize])

  return {
    turns,
    isStreaming,
    connectionStatus,
    toolCatalog,
    agentModels,
    autoApprove,
    setAgentModels,
    sendMessage,
    clearTurns,
    approvePlan,
    rejectPlan,
    setAutoApprove,
  }
}

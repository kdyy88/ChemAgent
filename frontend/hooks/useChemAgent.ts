import { useChatStore } from '@/store/chatStore'
import type { ToolMeta, Turn } from '@/lib/types'

/**
 * useChemAgent — the canonical public hook for all components.
 *
 * Wraps the Zustand store so components never import the store directly.
 * Returns only what components need; internal WebSocket plumbing is hidden.
 */
export function useChemAgent(): {
  turns: Turn[]
  isStreaming: boolean
  toolCatalog: Record<string, ToolMeta>
  sendMessage: (prompt: string) => void
  clearTurns: () => void
} {
  const turns = useChatStore((s) => s.turns)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const toolCatalog = useChatStore((s) => s.toolCatalog)
  const sendMessage = useChatStore((s) => s.sendMessage)
  const clearTurns = useChatStore((s) => s.clearTurns)

  return { turns, isStreaming, toolCatalog, sendMessage, clearTurns }
}

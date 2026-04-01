/**
 * useSSEChemAgent
 * ───────────────
 * Thin facade over `useSseStore` (Zustand) so components can call
 * the familiar hook API without worrying about the global store directly.
 *
 * Using a Zustand store means every component shares the same turns /
 * isStreaming state without creating isolated chat sessions.
 *
 * Usage
 * ─────
 *   const { turns, isStreaming, sendMessage, clearTurns } = useSSEChemAgent()
 */

'use client'

import { useSseStore } from '@/store/sseStore'

// ── Hook (thin facade) ────────────────────────────────────────────────────────

export function useSSEChemAgent() {
  return useSseStore()
}

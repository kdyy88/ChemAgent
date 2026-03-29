/**
 * useSSEChemAgent
 * ───────────────
 * Thin facade over `useSseStore` (Zustand) so components can call
 * the familiar hook API without worrying about the global store directly.
 *
 * Using a Zustand store means every component — including the header's
 * "New Chat" button and TeamSettingsPopover — shares the same turns /
 * isStreaming state without any WebSocket connection.
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

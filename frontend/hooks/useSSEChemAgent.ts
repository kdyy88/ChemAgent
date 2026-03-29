/**
 * useSSEChemAgent
 * ───────────────
 * React hook that drives the LangGraph SSE endpoint:
 *   POST /api/chat/stream → text/event-stream
 *
 * Transport: @microsoft/fetch-event-source
 *   - Supports POST bodies (native EventSource only does GET).
 *   - Auto-reconnects on network interruption.
 *   - Throws on non-2xx HTTP status (e.g. 422 validation error).
 *
 * State model
 * ───────────
 * Each call to `sendMessage()` creates a new SSETurn and streams events
 * into it until a `done` or `error` event arrives.  All turns are kept in
 * state so the UI can render a conversation history.
 *
 * Artifact rendering
 * ──────────────────
 * When the hook receives an `artifact` event:
 *   - kind === "molecule_image"  → append to turn.artifacts; render with <img>
 *   - kind === "descriptors"     → append to turn.artifacts; render with a card
 *
 * Usage
 * ─────
 *   const { turns, isStreaming, sendMessage, clearTurns } = useSSEChemAgent()
 */

'use client'

import { useCallback, useRef, useState } from 'react'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import type {
  SSEArtifactEvent,
  SSEError,
  SSEEvent,
  SSEShadowError,
  SSETurn,
} from '@/lib/sse-types'

// ── Config ────────────────────────────────────────────────────────────────────

/**
 * Base URL for the backend API.
 * Override via NEXT_PUBLIC_API_URL environment variable.
 */
const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '') ?? 'http://localhost:8000'

const STREAM_URL = `${API_BASE}/api/chat/stream`

// ── Utilities ─────────────────────────────────────────────────────────────────

function generateId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

function nodeLabel(node: string): string {
  const labels: Record<string, string> = {
    supervisor: 'Supervisor 路由分析中…',
    visualizer: 'Visualizer 渲染结构图…',
    analyst: 'Analyst 计算描述符…',
    shadow_lab: 'Shadow Lab 验证 SMILES…',
  }
  return labels[node] ?? `${node} 执行中…`
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useSSEChemAgent() {
  const [turns, setTurns] = useState<SSETurn[]>([])
  const [isStreaming, setIsStreaming] = useState(false)

  // Ref to abort the current SSE connection
  const abortCtrlRef = useRef<AbortController | null>(null)

  // Helper: immutably update the last turn
  const updateLastTurn = useCallback(
    (updater: (prev: SSETurn) => Partial<SSETurn>) => {
      setTurns((prev) => {
        if (prev.length === 0) return prev
        const last = prev[prev.length - 1]
        return [...prev.slice(0, -1), { ...last, ...updater(last) }]
      })
    },
    [],
  )

  // ── Event dispatcher ──────────────────────────────────────────────────────

  const handleEvent = useCallback(
    (ev: SSEEvent) => {
      switch (ev.type) {
        // ── Graph lifecycle ──────────────────────────────────────────────
        case 'run_started':
          // Already created the turn in sendMessage(); nothing extra needed.
          break

        case 'node_start':
          updateLastTurn(() => ({
            activeNode: ev.node,
            statusLabel: nodeLabel(ev.node),
          }))
          break

        case 'node_end':
          updateLastTurn((t) => ({
            activeNode: t.activeNode === ev.node ? null : t.activeNode,
            statusLabel: t.activeNode === ev.node ? '' : t.statusLabel,
          }))
          break

        // ── Streaming text ───────────────────────────────────────────────
        case 'token':
          updateLastTurn((t) => ({
            assistantText: t.assistantText + ev.content,
          }))
          break

        // ── Tool calls ───────────────────────────────────────────────────
        case 'tool_start':
          updateLastTurn((t) => ({
            toolCalls: [
              ...t.toolCalls,
              { tool: ev.tool, input: ev.input, done: false },
            ],
            statusLabel: `🔬 ${ev.tool} 执行中…`,
          }))
          break

        case 'tool_end':
          updateLastTurn((t) => ({
            toolCalls: t.toolCalls.map((tc) =>
              tc.tool === ev.tool && !tc.done ? { ...tc, done: true } : tc,
            ),
            statusLabel: `✅ ${ev.tool} 完成`,
          }))
          break

        // ── Artifacts ────────────────────────────────────────────────────
        case 'artifact':
          updateLastTurn((t) => ({
            artifacts: [...t.artifacts, ev as SSEArtifactEvent],
          }))
          break

        // ── Shadow Lab error ─────────────────────────────────────────────
        case 'shadow_error':
          updateLastTurn((t) => ({
            shadowErrors: [...t.shadowErrors, ev as SSEShadowError],
            statusLabel: '⚠️ Shadow Lab 发现 SMILES 错误，正在自我纠正…',
          }))
          break

        // ── Terminal events ──────────────────────────────────────────────
        case 'done':
          updateLastTurn(() => ({
            isStreaming: false,
            activeNode: null,
            statusLabel: '',
          }))
          setIsStreaming(false)
          break

        case 'error':
          updateLastTurn((t) => ({
            isStreaming: false,
            activeNode: null,
            statusLabel: '',
            assistantText:
              t.assistantText +
              `\n\n> ❌ **错误**: ${(ev as SSEError).error}`,
          }))
          setIsStreaming(false)
          break
      }
    },
    [updateLastTurn],
  )

  // ── Public API ────────────────────────────────────────────────────────────

  const sendMessage = useCallback(
    async (
      message: string,
      options: { activeSmiles?: string | null } = {},
    ) => {
      if (isStreaming) return

      const turnId = generateId()
      const sessionId = generateId()

      // Create the turn immediately with isStreaming:true
      const newTurn: SSETurn = {
        turnId,
        userMessage: message,
        assistantText: '',
        isStreaming: true,
        activeNode: null,
        toolCalls: [],
        artifacts: [],
        shadowErrors: [],
        statusLabel: 'Supervisor 路由分析中…',
      }
      setTurns((prev) => [...prev, newTurn])
      setIsStreaming(true)

      // Abort any previous stream
      abortCtrlRef.current?.abort()
      const ctrl = new AbortController()
      abortCtrlRef.current = ctrl

      await fetchEventSource(STREAM_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          session_id: sessionId,
          turn_id: turnId,
          active_smiles: options.activeSmiles ?? null,
        }),
        signal: ctrl.signal,

        // Called for each `data:` line
        onmessage(msg) {
          if (!msg.data) return
          try {
            const event = JSON.parse(msg.data) as SSEEvent
            handleEvent(event)
          } catch {
            // Silently ignore malformed JSON lines
          }
        },

        // Non-2xx HTTP status → surface as error, do NOT reconnect
        async onopen(response) {
          if (!response.ok) {
            const text = await response.text()
            updateLastTurn(() => ({
              isStreaming: false,
              statusLabel: '',
              assistantText: `❌ HTTP ${response.status}: ${text}`,
            }))
            setIsStreaming(false)
            throw new Error(`HTTP ${response.status}`)
          }
        },

        // Network error / abort — mark turn as done
        onerror(err) {
          if ((err as Error)?.name === 'AbortError') return   // deliberate abort
          updateLastTurn(() => ({
            isStreaming: false,
            statusLabel: '',
            assistantText: `❌ 连接中断: ${(err as Error)?.message ?? err}`,
          }))
          setIsStreaming(false)
          throw err  // prevent auto-retry
        },
      })
    },
    [isStreaming, handleEvent, updateLastTurn],
  )

  const clearTurns = useCallback(() => {
    abortCtrlRef.current?.abort()
    setTurns([])
    setIsStreaming(false)
  }, [])

  return { turns, isStreaming, sendMessage, clearTurns }
}

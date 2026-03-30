/**
 * sseStore — global Zustand store for the LangGraph SSE chat.
 *
 * Previously the SSE state lived inside useSSEChemAgent's local useState,
 * which meant every component that called the hook got an isolated instance.
 * By moving it here any component can read `turns` / `isStreaming` and call
 * `clearTurns` without triggering a WebSocket connection.
 */

import { create } from 'zustand'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import type {
  SSEArtifactEvent,
  SSEError,
  SSEEvent,
  SSEInterrupt,
  SSEShadowError,
  SSEThinking,
  SSETurn,
} from '@/lib/sse-types'
import { useWorkspaceStore } from '@/store/workspaceStore'

// ── Config ────────────────────────────────────────────────────────────────────

const API_BASE =
  (typeof process !== 'undefined' &&
    (process.env.NEXT_PUBLIC_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_URL)?.replace(/\/$/, '')) ||
  (typeof window !== 'undefined' ? window.location.origin : '') ||
  'http://localhost:8000'

const STREAM_URL = `${API_BASE}/api/chat/stream`

// ── Helpers ───────────────────────────────────────────────────────────────────

function generateId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

function normalizeThinkingText(text: string): string {
  return text
    // Common tokenizer markers from some gateways/providers
    .replace(/[▁]/g, ' ')
    .replace(/[Ġ]/g, ' ')
    // Remove most ASCII control chars but keep newlines/tabs for readability
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function updateWorkspaceFromPayload(payload: Record<string, unknown>) {
  const nextSmiles =
    typeof payload.cleaned_smiles === 'string' ? payload.cleaned_smiles
    : typeof payload.canonical_smiles === 'string' ? payload.canonical_smiles
    : typeof payload.scaffold_smiles === 'string' ? payload.scaffold_smiles
    : typeof payload.smiles === 'string' ? payload.smiles
    : undefined

  const nextName = typeof payload.name === 'string' ? payload.name : undefined
  const workspace = useWorkspaceStore.getState()
  if (nextSmiles) workspace.setSmiles(nextSmiles)
  if (nextName) workspace.setName(nextName)
}

function appendThinkingStep(
  steps: SSEThinking[],
  entry: SSEThinking,
): SSEThinking[] {
  const text = normalizeThinkingText(entry.text)
  if (!text) return steps

  const next = [...steps]
  const last = next[next.length - 1]
  if (
    last &&
    last.done !== true &&
    entry.done === false &&
    last.source === entry.source &&
    last.iteration === entry.iteration
  ) {
    next[next.length - 1] = {
      ...last,
      text: `${last.text}${text}`,
      done: entry.done,
    }
    return next
  }

  if (last && last.source === entry.source && last.iteration === entry.iteration) {
    // Avoid duplicate final append when provider sends both streamed fragments
    // and a near-identical aggregated reasoning block.
    if (last.text === text || text.startsWith(last.text) || last.text.startsWith(text)) {
      next[next.length - 1] = { ...last, text: text.length >= last.text.length ? text : last.text, done: entry.done }
      return next
    }
  }

  next.push({ ...entry, text })
  return next
}



// ── State shape ───────────────────────────────────────────────────────────────

export interface InterruptContext {
  question: string
  options: string[]
  called_tools: string[]
  interrupt_id: string
  known_smiles?: string
}

export interface SseState {
  turns: SSETurn[]
  isStreaming: boolean
  sendMessage: (
    message: string,
    options?: { activeSmiles?: string | null; interruptContext?: InterruptContext }
  ) => Promise<void>
  clearTurns: () => void
}

/** Exported so components can reuse the same mapping. */
export function nodeLabel(node: string): string {
  const labels: Record<string, string> = {
    chem_agent: '🧠 智能体推理中…',
    tools_executor: '🛠️ 工具执行中…',
  }
  return labels[node] ?? `${node} 执行中…`
}

// ── Store ─────────────────────────────────────────────────────────────────────

// These live outside Zustand — no re-render on mutation.
let _abortCtrl: AbortController | null = null
/** Session ID persists for the whole conversation; reset only in clearTurns. */
let _sessionId: string | null = null
/**
 * LangGraph astream_events fires on_chain_start/on_chain_end for internal
 * sub-graph wrappers too, so the same node name can appear 2-4 times.
 * We track the nesting depth per node and only clear activeNode when the
 * outermost end event arrives (depth reaches 0).
 */
let _nodeDepth: Record<string, number> = {}

export const useSseStore = create<SseState>((set, get) => {
  // ── Private helpers ──────────────────────────────────────────────────────

  function updateLastTurn(updater: (prev: SSETurn) => Partial<SSETurn>) {
    set((state) => {
      if (state.turns.length === 0) return state
      const all = state.turns
      const last = all[all.length - 1]
      return { turns: [...all.slice(0, -1), { ...last, ...updater(last) }] }
    })
  }

  function handleEvent(ev: SSEEvent) {
    switch (ev.type) {
      case 'run_started':
        break

      case 'node_start': {
        // LangGraph fires on_chain_start for internal sub-graph wrappers too.
        // Track nesting depth: only update UI on the outermost (first) start.
        const prevDepth = _nodeDepth[ev.node] ?? 0
        _nodeDepth[ev.node] = prevDepth + 1
        if (prevDepth === 0) {
          updateLastTurn(() => ({
            activeNode: ev.node,
            statusLabel: nodeLabel(ev.node),
          }))
        }
        break
      }

      case 'node_end': {
        // Only clear activeNode when the outermost end event arrives.
        const depth = Math.max(0, (_nodeDepth[ev.node] ?? 1) - 1)
        _nodeDepth[ev.node] = depth
        if (depth === 0) {
          updateLastTurn((t) => ({
            activeNode: t.activeNode === ev.node ? null : t.activeNode,
            statusLabel: t.activeNode === ev.node ? '' : t.statusLabel,
          }))
        }
        break
      }

      case 'token':
        updateLastTurn((t) => ({
          assistantText: t.assistantText + ev.content,
        }))
        break

      case 'tool_start':
        updateLastTurn((t) => ({
          toolCalls: [
            ...t.toolCalls,
            { tool: ev.tool, input: ev.input, output: undefined, done: false },
          ],
          statusLabel: '🛠️ 工具执行中…',
        }))
        break

      case 'tool_end':
        updateLastTurn((t) => {
          const calls = [...t.toolCalls]
          // Find the last unfinished call with this tool name
          let lastIdx = -1
          for (let i = calls.length - 1; i >= 0; i--) {
            if (calls[i].tool === ev.tool && !calls[i].done) { lastIdx = i; break }
          }
          if (lastIdx !== -1) {
            calls[lastIdx] = {
              ...calls[lastIdx],
              output: typeof ev.output === 'object' && ev.output !== null
                ? (ev.output as Record<string, unknown>)
                : { raw: ev.output },
              done: true,
            }
            if (calls[lastIdx].output) {
              updateWorkspaceFromPayload(calls[lastIdx].output as Record<string, unknown>)
            }
          }
          return { toolCalls: calls, statusLabel: '🧠 正在整合工具结果…' }
        })
        break

      case 'artifact': {
        const artifact = ev as SSEArtifactEvent
        if ('smiles' in artifact && artifact.smiles) {
          useWorkspaceStore.getState().setSmiles(artifact.smiles)
        }
        updateLastTurn((t) => ({
          artifacts: [...t.artifacts, artifact],
        }))
        break
      }

      case 'shadow_error':
        updateLastTurn((t) => ({
          shadowErrors: [...t.shadowErrors, ev as SSEShadowError],
          statusLabel: '⚠️ 正在修正结构问题…',
          thinkingSteps: appendThinkingStep(t.thinkingSteps, {
            type: 'thinking',
            text: `检测到结构问题：${(ev as SSEShadowError).error}`,
            iteration: 0,
            done: true,
            source: 'tools_executor',
            session_id: ev.session_id,
            turn_id: ev.turn_id,
          }),
        }))
        break

      case 'interrupt': {
        const iv = ev as SSEInterrupt
        // Find the known SMILES from the last completed tool output if available
        updateLastTurn((t) => {
          const pubchemOutput = [...t.toolCalls]
            .reverse()
            .find((tc) => tc.tool === 'tool_pubchem_lookup' && tc.done)?.output
          const knownSmiles =
            (pubchemOutput as Record<string, unknown> | undefined)?.canonical_smiles as string | undefined
          return {
            isStreaming: false,
            activeNode: null,
            statusLabel: '🙋 等待您的回复…',
            thinkingSteps: appendThinkingStep(t.thinkingSteps, {
              type: 'thinking',
              text: `需要用户澄清：${iv.question}`,
              iteration: 0,
              done: true,
              source: 'chem_agent',
              session_id: iv.session_id,
              turn_id: iv.turn_id,
            }),
            pendingInterrupt: {
              question: iv.question,
              options: iv.options,
              called_tools: iv.called_tools,
              interrupt_id: iv.interrupt_id,
              known_smiles: knownSmiles,
            },
          }
        })
        set({ isStreaming: false })
        _abortCtrl?.abort()
        _abortCtrl = null
        break
      }

      case 'thinking': {
        const thinkingEv = ev as SSEThinking
        updateLastTurn((t) => {
          const prefixMap: Record<string, string> = {
            chem_agent: '[chem_agent] ',
            tools_executor: '[tools_executor] ',
            llm_reasoning: '[llm] ',
          }
          const prefix = thinkingEv.source ? `${prefixMap[thinkingEv.source] ?? '[reasoning] '}` : ''
          return {
            thinkingSteps: appendThinkingStep(t.thinkingSteps, {
              ...thinkingEv,
              text: `${prefix}${thinkingEv.text}`,
            }),
          }
        })
        break
      }

      case 'done':
        updateLastTurn(() => ({
          isStreaming: false,
          activeNode: null,
          statusLabel: '',
        }))
        set({ isStreaming: false })
        _nodeDepth = {}
        // Abort the controller so fetchEventSource does NOT retry after the
        // stream closes naturally — without this, it fires 10+ duplicate POSTs.
        _abortCtrl?.abort()
        _abortCtrl = null
        break

      case 'error':
        updateLastTurn((t) => ({
          isStreaming: false,
          activeNode: null,
          statusLabel: '',
          assistantText:
            t.assistantText + `\n\n> ❌ **错误**: ${(ev as SSEError).error}`,
        }))
        set({ isStreaming: false })
        _nodeDepth = {}
        _abortCtrl?.abort()
        _abortCtrl = null
        break
    }
  }

  // ── Public actions ───────────────────────────────────────────────────────

  return {
    turns: [],
    isStreaming: false,

    clearTurns: () => {
      _abortCtrl?.abort()
      _abortCtrl = null
      _sessionId = null
      _nodeDepth = {}
      set({ turns: [], isStreaming: false })
    },

    sendMessage: async (message, options = {}) => {
      if (get().isStreaming) return

      // Reuse session across turns; create once per conversation
      if (!_sessionId) _sessionId = generateId()
      const turnId = generateId()

      const newTurn: SSETurn = {
        turnId,
        userMessage: message,
        assistantText: '',
        isStreaming: true,
        activeNode: null,
        toolCalls: [],
        artifacts: [],
        shadowErrors: [],
        statusLabel: '🧠 智能体推理中…',
        pendingInterrupt: undefined,
        thinkingSteps: [],
      }

      set((state) => ({ turns: [...state.turns, newTurn], isStreaming: true }))

      _abortCtrl?.abort()
      const ctrl = new AbortController()
      _abortCtrl = ctrl

      try {
        await fetchEventSource(STREAM_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message,
            session_id: _sessionId,
            turn_id: turnId,
            active_smiles: options.activeSmiles ?? null,
            interrupt_context: options.interruptContext ?? null,
            // Send completed prior turns so the backend has full conversation context
            history: get().turns
              .filter((t) => !t.isStreaming && t.assistantText.trim())
              .flatMap((t) => [
                { role: 'human', content: t.userMessage },
                { role: 'assistant', content: t.assistantText },
              ]),
          }),
          signal: ctrl.signal,

          onmessage(msg) {
            if (!msg.data) return
            try {
              handleEvent(JSON.parse(msg.data) as SSEEvent)
            } catch {
              // Silently ignore malformed JSON
            }
          },

          async onopen(response) {
            if (!response.ok) {
              const text = await response.text()
              updateLastTurn(() => ({
                isStreaming: false,
                statusLabel: '',
                assistantText: `❌ HTTP ${response.status}: ${text}`,
              }))
              set({ isStreaming: false })
              throw new Error(`HTTP ${response.status}`)
            }
          },

          onerror(err) {
            // Always throw so fetchEventSource never retries — whether the abort
            // was intentional (AbortError from our controller) or a genuine network
            // failure.  Genuine errors are already surfaced via the 'error' SSE event.
            if ((err as Error)?.name !== 'AbortError') {
              updateLastTurn(() => ({
                isStreaming: false,
                statusLabel: '',
                assistantText: `❌ 连接中断: ${(err as Error)?.message ?? err}`,
              }))
              set({ isStreaming: false })
            }
            throw err
          },
        })
      } catch (err) {
        // Swallow intentional AbortErrors (triggered by our own abort on done/error).
        // All other errors are already surfaced in the UI by onerror above.
        if ((err as Error)?.name !== 'AbortError') throw err
      }
    },
  }
})

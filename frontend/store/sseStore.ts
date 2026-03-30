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
  SSETaskUpdate,
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

const WORKSPACE_SMILES_KEYS = [
  'cleaned_smiles',
  'canonical_smiles',
  'scaffold_smiles',
  'smiles',
] as const

const NODE_LABELS: Record<string, string> = {
  task_router: '🧭 正在判断任务复杂度…',
  planner_node: '🗂️ 正在生成任务清单…',
  chem_agent: '🧠 智能体推理中…',
  tools_executor: '🛠️ 工具执行中…',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function generateId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36)
}

function normalizeThinkingText(text: string): string {
  return text
    // Common tokenizer markers from some gateways/providers
    .replace(/[▁]/g, ' ')
    .replace(/[Ġ]/g, ' ')
    // Remove most ASCII control chars but keep newlines/tabs for readability
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
}

function updateWorkspaceFromPayload(payload: Record<string, unknown>) {
  const nextSmiles = WORKSPACE_SMILES_KEYS.find(
    (key) => typeof payload[key] === 'string',
  )

  const nextName = typeof payload.name === 'string' ? payload.name : undefined
  const workspace = useWorkspaceStore.getState()
  if (nextSmiles) workspace.setSmiles(payload[nextSmiles] as string)
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
    const lastTrimmed = last.text.trim()
    const textTrimmed = text.trim()
    if (
      lastTrimmed === textTrimmed ||
      textTrimmed.startsWith(lastTrimmed) ||
      lastTrimmed.startsWith(textTrimmed)
    ) {
      next[next.length - 1] = { ...last, text: text.length >= last.text.length ? text : last.text, done: entry.done }
      return next
    }
  }

  next.push({ ...entry, text })
  return next
}



// ── State shape ───────────────────────────────────────────────────────────────

export interface InterruptContext {
  interrupt_id: string
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
  return NODE_LABELS[node] ?? `${node} 执行中…`
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
let _unfinishedToolCallIndexes: Record<string, Record<string, number[]>> = {}
let _latestToolOutputs: Record<string, Record<string, Record<string, unknown>>> = {}

function resetStreamCaches() {
  _nodeDepth = {}
  _unfinishedToolCallIndexes = {}
  _latestToolOutputs = {}
}

function abortActiveStream() {
  _abortCtrl?.abort()
  _abortCtrl = null
}

function pushUnfinishedToolCallIndex(turnId: string, tool: string, index: number) {
  const turnIndexes = (_unfinishedToolCallIndexes[turnId] ??= {})
  const toolIndexes = (turnIndexes[tool] ??= [])
  toolIndexes.push(index)
}

function popUnfinishedToolCallIndex(turnId: string, tool: string): number | undefined {
  const toolIndexes = _unfinishedToolCallIndexes[turnId]?.[tool]
  const index = toolIndexes?.pop()
  if (toolIndexes?.length === 0 && _unfinishedToolCallIndexes[turnId]) {
    delete _unfinishedToolCallIndexes[turnId][tool]
  }
  return index
}

function rememberLatestToolOutput(turnId: string, tool: string, output: Record<string, unknown>) {
  const turnOutputs = (_latestToolOutputs[turnId] ??= {})
  turnOutputs[tool] = output
}

function readLatestToolOutput(turnId: string, tool: string): Record<string, unknown> | undefined {
  return _latestToolOutputs[turnId]?.[tool]
}

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

  function finishStream() {
    set({ isStreaming: false })
    abortActiveStream()
    resetStreamCaches()
  }

  function stopStreamWithMessage(message: string) {
    updateLastTurn((t) => ({
      isStreaming: false,
      activeNode: null,
      statusLabel: '',
      assistantText: message ? `${t.assistantText}${message}` : t.assistantText,
    }))
    finishStream()
  }

  function stopStreamStatus(statusLabel: string) {
    updateLastTurn(() => ({
      isStreaming: false,
      activeNode: null,
      statusLabel,
    }))
    finishStream()
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
        updateLastTurn((t) => {
          pushUnfinishedToolCallIndex(t.turnId, ev.tool, t.toolCalls.length)
          return {
            toolCalls: [
              ...t.toolCalls,
              { tool: ev.tool, input: ev.input, output: undefined, done: false },
            ],
            statusLabel: '🛠️ 工具执行中…',
          }
        })
        break

      case 'tool_end':
        if (typeof ev.output === 'object' && ev.output !== null) {
          updateWorkspaceFromPayload(ev.output as Record<string, unknown>)
        }
        updateLastTurn((t) => {
          const calls = [...t.toolCalls]
          const nextOutput = typeof ev.output === 'object' && ev.output !== null
            ? (ev.output as Record<string, unknown>)
            : { raw: ev.output }
          const indexedIdx = popUnfinishedToolCallIndex(t.turnId, ev.tool)
          const lastIdx = indexedIdx ?? calls.findLastIndex((call) => call.tool === ev.tool && !call.done)

          if (lastIdx !== -1) {
            calls[lastIdx] = {
              ...calls[lastIdx],
              output: nextOutput,
              done: true,
            }
            if (typeof ev.output === 'object' && ev.output !== null) {
              rememberLatestToolOutput(t.turnId, ev.tool, ev.output as Record<string, unknown>)
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

      case 'task_update': {
        const taskEvent = ev as SSETaskUpdate
        const activeTask = taskEvent.tasks.find((task) => task.status === 'in_progress')
        updateLastTurn(() => ({
          tasks: taskEvent.tasks,
          statusLabel: activeTask ? `📋 正在执行任务 ${activeTask.id}` : '📋 任务清单已更新',
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
        const currentTurnId = get().turns.at(-1)?.turnId
        const knownSmiles = iv.known_smiles ?? (
          currentTurnId
            ? readLatestToolOutput(currentTurnId, 'tool_pubchem_lookup')?.canonical_smiles as string | undefined
            : undefined
        )

        updateLastTurn((t) => {
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
        stopStreamStatus('🙋 等待您的回复…')
        break
      }

      case 'thinking': {
        const thinkingEv = ev as SSEThinking
        updateLastTurn((t) => ({
          thinkingSteps: appendThinkingStep(t.thinkingSteps, thinkingEv),
        }))
        break
      }

      case 'done':
        updateLastTurn(() => ({
          isStreaming: false,
          activeNode: null,
          statusLabel: '',
        }))
        finishStream()
        break

      case 'error':
        stopStreamWithMessage(`\n\n> ❌ **错误**: ${(ev as SSEError).error}`)
        break
    }
  }

  // ── Public actions ───────────────────────────────────────────────────────

  return {
    turns: [],
    isStreaming: false,

    clearTurns: () => {
      abortActiveStream()
      _sessionId = null
      resetStreamCaches()
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
        tasks: get().turns.at(-1)?.tasks ?? [],
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
              finishStream()
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
              finishStream()
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

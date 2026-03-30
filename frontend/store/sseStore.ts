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
    supervisor:  '🧭 思考中…',
    responder:   '💬 组织回答中…',
    researcher:  '🔭 调研中（PubChem + 联网分析）…',
    visualizer:  '🎨 渲染 2D 结构图…',
    analyst:     '🔬 计算分子描述符…',
    prep:        '⚗️ 格式转换 / 构象 / 对接准备中…',
    shadow_lab:  '🧪 Shadow Lab 验证 SMILES…',
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
          statusLabel: `🔬 ${ev.tool} 执行中…`,
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
          }
          return { toolCalls: calls, statusLabel: `✅ ${ev.tool} 完成` }
        })
        break

      case 'artifact':
        updateLastTurn((t) => ({
          artifacts: [...t.artifacts, ev as SSEArtifactEvent],
        }))
        break

      case 'shadow_error':
        updateLastTurn((t) => ({
          shadowErrors: [...t.shadowErrors, ev as SSEShadowError],
          statusLabel: '⚠️ Shadow Lab 发现 SMILES 错误，正在自我纠正…',
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
        const source = thinkingEv.source || 'unknown'
        
        // Add source prefix for better context
        const sourcePrefix = {
          'intent': '🎯 意图识别',
          'supervisor': '🧭 路由决策',
          'researcher': '🔭 研究推理',
          'visualizer': '🎨 可视化',
          'analyst': '🔬 分析',
          'prep': '⚗️ 准备',
        }[source] || '💭 思考'
        
        const displayText = source && source !== 'unknown' 
          ? `${sourcePrefix}: ${thinkingEv.text}`
          : thinkingEv.text
        
        updateLastTurn((t) => {
          const steps = [...t.thinkingSteps]
          const last = steps.length > 0 ? steps[steps.length - 1] : null
          // Append to the current step when:
          //   - same iteration AND the step has not been marked done yet
          // Create a new step when:
          //   - no prior steps, OR different iteration, OR prior step is done
          if (
            last !== null &&
            last.iteration === thinkingEv.iteration &&
            last.done !== true
          ) {
            steps[steps.length - 1] = {
              ...last,
              text: last.text + displayText,
              done: thinkingEv.done ?? last.done,
            }
          } else {
            // New iteration or prior step completed — start a fresh step.
            steps.push({ 
              text: displayText, 
              iteration: thinkingEv.iteration, 
              done: thinkingEv.done 
            })
          }
          return { thinkingSteps: steps }
        })
        break
      }

      case 'orchestration_step_start': {
        const stepEv = ev as any
        updateLastTurn((t) => {
          const orchestrationSteps = [...(t.orchestrationSteps ?? [])]
          // Initialize or update step
          if (orchestrationSteps[stepEv.step_index]) {
            orchestrationSteps[stepEv.step_index] = {
              ...orchestrationSteps[stepEv.step_index],
              status: 'running',
            }
          } else {
            orchestrationSteps[stepEv.step_index] = {
              step_index: stepEv.step_index,
              tool_name: stepEv.tool_name,
              status: 'running',
              input_params: stepEv.input_params,
            }
          }
          return {
            orchestrationSteps,
            statusLabel: `🔗 执行工具: ${stepEv.tool_name}…`,
          }
        })
        break
      }

      case 'orchestration_step_end': {
        const stepEv = ev as any
        updateLastTurn((t) => {
          const orchestrationSteps = [...(t.orchestrationSteps ?? [])]
          orchestrationSteps[stepEv.step_index] = {
            step_index: stepEv.step_index,
            tool_name: stepEv.tool_name,
            status: stepEv.status,
            output: stepEv.output,
            error: stepEv.error,
          }
          return {
            orchestrationSteps,
            statusLabel: stepEv.status === 'success' 
              ? `✅ ${stepEv.tool_name} 完成`
              : `❌ ${stepEv.tool_name} 失败`,
          }
        })
        break
      }

      case 'orchestration_complete': {
        const completeEv = ev as any
        updateLastTurn((t) => ({
          statusLabel: completeEv.success 
            ? `✅ 工具链完成 (${completeEv.total_steps} 步)`
            : `❌ 工具链失败: ${completeEv.error_message}`,
        }))
        break
      }

      case 'token': {
        // Summarizer streams final conclusion via token events
        const tokenEv = ev as { content: string }
        updateLastTurn((t) => ({
          assistantText: tokenEv.content,
        }))
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
        statusLabel: '🧭 Supervisor 路由分析中…',
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

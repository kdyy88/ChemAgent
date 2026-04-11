import { fetchEventSource } from '@microsoft/fetch-event-source'
import type {
  SSEApprovalRequired,
  SSEArtifactEvent,
  SSEError,
  SSEEvent,
  SSEInterrupt,
  SSEPendingApproval,
  SSEPendingInterrupt,
  SSEPlanApprovalRequest,
  SSEPlanModified,
  SSESendMessageOptions,
  SSEShadowError,
  SSETaskItem,
  SSETaskUpdate,
  SSEThinking,
  SSEUsage,
} from '@/lib/sse-types'
import { translateStreamError } from '@/lib/i18n/sse-interceptor'

const API_BASE =
  (typeof process !== 'undefined' &&
    (process.env.NEXT_PUBLIC_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_URL)?.replace(/\/$/, '')) ||
  (typeof window !== 'undefined' ? window.location.origin : '') ||
  'http://localhost:8000'

const STREAM_URL = `${API_BASE}/api/v1/chat/stream`
const APPROVE_URL = `${API_BASE}/api/v1/chat/approve`
const SILENT_TOOLS = new Set(['tool_update_task_status'])

type ToolOutput = Record<string, unknown>

interface SSEClientHandlers {
  startTurn: (turnId: string, message: string, previousTasks: SSETaskItem[]) => void
  activateNode: (node: string) => void
  clearNode: (node: string) => void
  appendAssistantText: (text: string) => void
  addToolCall: (tool: string, input: Record<string, unknown>) => number
  completeToolCall: (index: number, output: ToolOutput) => void
  addArtifact: (artifact: SSEArtifactEvent) => void
  updateTasks: (tasks: SSETaskItem[]) => void
  addShadowError: (error: SSEShadowError) => void
  appendThinking: (thinking: SSEThinking) => void
  recordUsage: (usage: SSEUsage) => void
  setPendingInterrupt: (interrupt: SSEPendingInterrupt) => void
  setPendingApproval: (approval: SSEPendingApproval) => void
  completeTurn: () => void
  failTurn: (message: string) => void
  handleHttpError: (status: number, text: string) => void
  handleConnectionError: (message: string) => void
}

interface SendMessageArgs {
  message: string
  previousTasks: SSETaskItem[]
  options?: SSESendMessageOptions
  handlers: SSEClientHandlers
}

function generateId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36)
}

interface SendApprovalArgs {
  sessionId: string
  turnId: string
  approvalLabel: string
  action: 'approve' | 'reject' | 'modify'
  args?: Record<string, unknown>
  planId?: string
  handlers: Omit<SSEClientHandlers, 'startTurn'>
}

export class SSEClient {
  private abortCtrl: AbortController | null = null
  /** Exposed read-only so the store can pass it to sendApproval. */
  sessionId: string | null = null
  private nodeDepth: Record<string, number> = {}
  private unfinishedToolCallIndexes: Record<string, Record<string, number[]>> = {}
  private latestToolOutputs: Record<string, Record<string, ToolOutput>> = {}
  /**
   * Tracks how many `tool_run_sub_agent` calls are currently active.
   * Any thinking events that arrive while this is > 0 are retagged with
   * source='sub_agent' so ResearchThinking can visually indent them.
   */
  private subAgentCallDepth = 0

  clearConversation() {
    this.abortActiveStream()
    this.sessionId = null
    this.resetStreamCaches()
  }

  async sendMessage({ message, previousTasks, options = {}, handlers }: SendMessageArgs) {
    if (!this.sessionId) this.sessionId = generateId()

    const turnId = generateId()
    handlers.startTurn(turnId, message, previousTasks)
    let terminalEventSeen = false

    this.abortActiveStream()
    const ctrl = new AbortController()
    this.abortCtrl = ctrl

    try {
      await fetchEventSource(STREAM_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          session_id: this.sessionId,
          turn_id: turnId,
          model: options.model ?? null,
          active_smiles: options.activeSmiles ?? null,
          interrupt_context: options.interruptContext ?? null,
        }),
        signal: ctrl.signal,
        openWhenHidden: true,

        onmessage: (msg) => {
          if (!msg.data) return

          try {
            const event = JSON.parse(msg.data) as SSEEvent
            if (event.type === 'done' || event.type === 'error' || event.type === 'interrupt' || event.type === 'approval_required' || event.type === 'plan_approval_request') {
              terminalEventSeen = true
            }
            this.handleEvent(event, turnId, handlers)
          } catch {
            // Silently ignore malformed JSON payloads.
          }
        },

        onclose: () => {
          if (!terminalEventSeen && !ctrl.signal.aborted) {
            throw new Error('SSE stream closed before a terminal event was received')
          }
        },

        onopen: async (response) => {
          if (!response.ok) {
            const text = await response.text()
            handlers.handleHttpError(response.status, text)
            this.finishStream()
            throw new Error(`HTTP ${response.status}`)
          }
        },

        onerror: (err) => {
          if ((err as Error)?.name !== 'AbortError') {
            handlers.handleConnectionError((err as Error)?.message ?? String(err))
            this.finishStream()
          }
          throw err
        },
      })
    } catch (err) {
      if ((err as Error)?.name !== 'AbortError') throw err
    }
  }

  private handleEvent(ev: SSEEvent, turnId: string, handlers: SSEClientHandlers) {
    switch (ev.type) {
      case 'run_started':
        return

      case 'node_start': {
        const prevDepth = this.nodeDepth[ev.node] ?? 0
        this.nodeDepth[ev.node] = prevDepth + 1
        if (prevDepth === 0) handlers.activateNode(ev.node)
        return
      }

      case 'node_end': {
        const depth = Math.max(0, (this.nodeDepth[ev.node] ?? 1) - 1)
        this.nodeDepth[ev.node] = depth
        if (depth === 0) handlers.clearNode(ev.node)
        return
      }

      case 'token':
        if (ev.source === 'sub_agent') {
          handlers.appendThinking({
            type: 'thinking',
            text: ev.content,
            iteration: 0,
            done: false,
            source: `sub_agent:${ev.node}`,
            category: 'llm',
            importance: 'high',
            group_key: `sub_agent:${ev.node}`,
            session_id: ev.session_id,
            turn_id: ev.turn_id,
          })
          return
        }
        handlers.appendAssistantText(ev.content)
        return

      case 'usage':
        handlers.recordUsage(ev as SSEUsage)
        return

      case 'tool_start': {
        // Track sub-agent activation BEFORE the silent-tool skip so the depth
        // counter is correct even though tool_run_sub_agent is in SILENT_TOOLS.
        if (ev.tool === 'tool_run_sub_agent') this.subAgentCallDepth++
        if (SILENT_TOOLS.has(ev.tool)) return
        const index = handlers.addToolCall(ev.tool, ev.input)
        this.pushUnfinishedToolCallIndex(turnId, ev.tool, index)
        return
      }

      case 'tool_end': {
        if (ev.tool === 'tool_run_sub_agent') {
          this.subAgentCallDepth = Math.max(0, this.subAgentCallDepth - 1)
        }
        if (SILENT_TOOLS.has(ev.tool)) return
        const nextOutput = typeof ev.output === 'object' && ev.output !== null
          ? (ev.output as ToolOutput)
          : { raw: ev.output }

        const index = this.popUnfinishedToolCallIndex(turnId, ev.tool)
        if (index !== undefined) {
          if (typeof ev.output === 'object' && ev.output !== null) {
            this.rememberLatestToolOutput(turnId, ev.tool, ev.output as ToolOutput)
          }
          handlers.completeToolCall(index, nextOutput)
        }
        return
      }

      case 'artifact':
        handlers.addArtifact(ev as SSEArtifactEvent)
        return

      case 'task_update':
        handlers.updateTasks((ev as SSETaskUpdate).tasks)
        return

      case 'shadow_error': {
        const error = ev as SSEShadowError
        handlers.addShadowError(error)
        // translateStreamError produces the localized "Structure issue detected: …" string
        handlers.appendThinking({
          type: 'thinking',
          text: translateStreamError(error.error).replace(/\n\n> ❌ \*\*.*?\*\*: /, '⚠️ '),
          iteration: 0,
          done: true,
          source: 'tools_executor',
          session_id: ev.session_id,
          turn_id: ev.turn_id,
        })
        return
      }

      case 'interrupt': {
        const interruptEvent = ev as SSEInterrupt
        const fallbackSmiles = this.readLatestToolOutput(turnId, 'tool_pubchem_lookup')?.canonical_smiles
        handlers.setPendingInterrupt({
          question: interruptEvent.question,
          options: interruptEvent.options,
          called_tools: interruptEvent.called_tools,
          interrupt_id: interruptEvent.interrupt_id,
          known_smiles:
            interruptEvent.known_smiles ?? (typeof fallbackSmiles === 'string' ? fallbackSmiles : undefined),
        })
        this.finishStream()
        return
      }

      case 'approval_required': {
        const approvalEvent = ev as SSEApprovalRequired
        handlers.setPendingApproval({
          kind: 'tool',
          tool_name: approvalEvent.tool_name,
          args: approvalEvent.args,
          tool_call_id: approvalEvent.tool_call_id,
          interrupt_id: approvalEvent.interrupt_id,
        })
        this.finishStream()
        return
      }

      case 'plan_approval_request': {
        const approvalEvent = ev as SSEPlanApprovalRequest
        handlers.setPendingApproval({
          kind: 'plan',
          plan_id: approvalEvent.plan_id,
          plan_file_ref: approvalEvent.plan_file_ref,
          summary: approvalEvent.summary,
          status: approvalEvent.status,
          mode: approvalEvent.mode,
          interrupt_id: approvalEvent.interrupt_id,
        })
        this.finishStream()
        return
      }

      case 'plan_modified': {
        const modifiedEvent = ev as SSEPlanModified
        handlers.setPendingApproval({
          kind: 'plan',
          plan_id: modifiedEvent.plan_id,
          plan_file_ref: modifiedEvent.plan_file_ref,
          summary: modifiedEvent.summary,
          status: modifiedEvent.status,
          mode: 'plan',
          interrupt_id: '',
        })
        handlers.appendThinking({
          type: 'thinking',
          text: '计划已更新，仍待最终审批。',
          iteration: 0,
          done: true,
          source: 'chem_agent',
          category: 'status',
          importance: 'high',
          session_id: modifiedEvent.session_id,
          turn_id: modifiedEvent.turn_id,
        })
        return
      }

      case 'thinking': {
        const thinkingEv = ev as SSEThinking
        // While a sub-agent is running, thinking events from the main engine's
        // tool executor and LLM reasoning pipeline actually originate inside the
        // sub-agent. Retag them so ResearchThinking can indent them visually.
        if (
          this.subAgentCallDepth > 0 &&
          (thinkingEv.source === 'tools_executor' || thinkingEv.source === 'llm_reasoning')
        ) {
          // category='error' thinking events carry raw tool-failure text (e.g.
          // "校验 SMILES失败：RDKit 无法解析..."). Suppress them for sub-agent
          // tool calls — matching the main agent's behaviour where the source is
          // 'tools_executor' so reasoningText is never populated for these steps.
          if (thinkingEv.category === 'error') return
          handlers.appendThinking({
            ...thinkingEv,
            source: 'sub_agent',
            group_key: thinkingEv.group_key
              ? `sub_agent::${thinkingEv.group_key}`
              : 'sub_agent',
          })
          return
        }
        handlers.appendThinking(thinkingEv)
        return
      }

      case 'done':
        handlers.completeTurn()
        this.finishStream()
        return

      case 'error':
        handlers.failTurn(translateStreamError((ev as SSEError).error))
        this.finishStream()
        return
    }
  }

  private resetStreamCaches() {
    this.nodeDepth = {}
    this.unfinishedToolCallIndexes = {}
    this.latestToolOutputs = {}
    this.subAgentCallDepth = 0
  }

  private finishStream() {
    this.abortActiveStream()
    this.resetStreamCaches()
  }

  private abortActiveStream() {
    this.abortCtrl?.abort()
    this.abortCtrl = null
  }

  private pushUnfinishedToolCallIndex(turnId: string, tool: string, index: number) {
    const turnIndexes = (this.unfinishedToolCallIndexes[turnId] ??= {})
    const toolIndexes = (turnIndexes[tool] ??= [])
    toolIndexes.push(index)
  }

  private popUnfinishedToolCallIndex(turnId: string, tool: string): number | undefined {
    const toolIndexes = this.unfinishedToolCallIndexes[turnId]?.[tool]
    const index = toolIndexes?.pop()
    if (toolIndexes?.length === 0 && this.unfinishedToolCallIndexes[turnId]) {
      delete this.unfinishedToolCallIndexes[turnId][tool]
    }
    return index
  }

  private rememberLatestToolOutput(turnId: string, tool: string, output: ToolOutput) {
    const turnOutputs = (this.latestToolOutputs[turnId] ??= {})
    turnOutputs[tool] = output
  }

  private readLatestToolOutput(turnId: string, tool: string): ToolOutput | undefined {
    return this.latestToolOutputs[turnId]?.[tool]
  }

  /**
   * Resume a heavy-tool Hard Breakpoint after the user makes a decision.
  * POSTs to /api/v1/chat/approve and streams the continuation exactly like
   * sendMessage does, reusing the same handlers.
   */
  async sendApproval({ sessionId, turnId, approvalLabel, action, args = {}, planId, handlers }: SendApprovalArgs) {
    this.abortActiveStream()
    const ctrl = new AbortController()
    this.abortCtrl = ctrl

    let terminalEventSeen = false

    // Create a fake startTurn-compatible invocation so the store can open a new turn.
    // We supply a human-readable label so the user sees what they approved.
    ;(handlers as SSEClientHandlers).startTurn?.(turnId, approvalLabel, [])

    try {
      await fetchEventSource(APPROVE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, turn_id: turnId, plan_id: planId ?? null, action, args }),
        signal: ctrl.signal,
        openWhenHidden: true,

        onmessage: (msg) => {
          if (!msg.data) return
          try {
            const event = JSON.parse(msg.data) as SSEEvent
            if (event.type === 'done' || event.type === 'error' || event.type === 'interrupt' || event.type === 'approval_required' || event.type === 'plan_approval_request') {
              terminalEventSeen = true
            }
            this.handleEvent(event, turnId, handlers as SSEClientHandlers)
          } catch {
            // Silently ignore malformed JSON payloads.
          }
        },

        onclose: () => {
          if (!terminalEventSeen && !ctrl.signal.aborted) {
            throw new Error('SSE stream closed before a terminal event was received')
          }
        },

        onopen: async (response) => {
          if (!response.ok) {
            const text = await response.text()
            handlers.handleHttpError(response.status, text)
            this.finishStream()
            throw new Error(`HTTP ${response.status}`)
          }
        },

        onerror: (err) => {
          if ((err as Error)?.name !== 'AbortError') {
            handlers.handleConnectionError((err as Error)?.message ?? String(err))
            this.finishStream()
          }
          throw err
        },
      })
    } catch (err) {
      if ((err as Error)?.name !== 'AbortError') throw err
    }
  }
}

export const sseClient = new SSEClient()
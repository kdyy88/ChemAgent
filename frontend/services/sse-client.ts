import { fetchEventSource } from '@microsoft/fetch-event-source'
import type {
  SSEArtifactEvent,
  SSEError,
  SSEEvent,
  SSEInterrupt,
  SSEPendingInterrupt,
  SSESendMessageOptions,
  SSEShadowError,
  SSETaskItem,
  SSETaskUpdate,
  SSEThinking,
} from '@/lib/sse-types'

const API_BASE =
  (typeof process !== 'undefined' &&
    (process.env.NEXT_PUBLIC_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_URL)?.replace(/\/$/, '')) ||
  (typeof window !== 'undefined' ? window.location.origin : '') ||
  'http://localhost:8000'

const STREAM_URL = `${API_BASE}/api/chat/stream`
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
  setPendingInterrupt: (interrupt: SSEPendingInterrupt) => void
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

export class SSEClient {
  private abortCtrl: AbortController | null = null
  private sessionId: string | null = null
  private nodeDepth: Record<string, number> = {}
  private unfinishedToolCallIndexes: Record<string, Record<string, number[]>> = {}
  private latestToolOutputs: Record<string, Record<string, ToolOutput>> = {}

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
          active_smiles: options.activeSmiles ?? null,
          interrupt_context: options.interruptContext ?? null,
        }),
        signal: ctrl.signal,
        openWhenHidden: true,

        onmessage: (msg) => {
          if (!msg.data) return

          try {
            const event = JSON.parse(msg.data) as SSEEvent
            if (event.type === 'done' || event.type === 'error' || event.type === 'interrupt') {
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
        handlers.appendAssistantText(ev.content)
        return

      case 'tool_start': {
        if (SILENT_TOOLS.has(ev.tool)) return
        const index = handlers.addToolCall(ev.tool, ev.input)
        this.pushUnfinishedToolCallIndex(turnId, ev.tool, index)
        return
      }

      case 'tool_end': {
        if (SILENT_TOOLS.has(ev.tool)) return
        const nextOutput = typeof ev.output === 'object' && ev.output !== null
          ? (ev.output as ToolOutput)
          : { raw: ev.output }

        const index = this.popUnfinishedToolCallIndex(turnId, ev.tool)
        if (typeof ev.output === 'object' && ev.output !== null) {
          this.rememberLatestToolOutput(turnId, ev.tool, ev.output as ToolOutput)
        }
        if (index !== undefined) {
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
        handlers.appendThinking({
          type: 'thinking',
          text: `检测到结构问题：${error.error}`,
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

      case 'thinking':
        handlers.appendThinking(ev as SSEThinking)
        return

      case 'done':
        handlers.completeTurn()
        this.finishStream()
        return

      case 'error':
        handlers.failTurn(`\n\n> ❌ **错误**: ${(ev as SSEError).error}`)
        this.finishStream()
        return
    }
  }

  private resetStreamCaches() {
    this.nodeDepth = {}
    this.unfinishedToolCallIndexes = {}
    this.latestToolOutputs = {}
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
}

export const sseClient = new SSEClient()
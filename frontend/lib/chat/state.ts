import type { Artifact, AgentModelConfig, ServerEvent, Step, ToolMeta, Turn } from '@/lib/types'

export type PendingTurn = {
  turnId: string
  prompt: string
}

export type ChatStateSlice = {
  sessionId: string | null
  turns: Turn[]
  isStreaming: boolean
  toolCatalog: Record<string, ToolMeta>
  agentModels: AgentModelConfig
}

function createTurnId(): string {
  return globalThis.crypto.randomUUID()
}

export function createTurn(prompt: string): Turn {
  return {
    id: createTurnId(),
    userMessage: prompt,
    steps: [],
    artifacts: [],
    status: 'thinking',
    startedAt: 0,
  }
}

function normalizeArtifact(
  raw: Extract<ServerEvent, { type: 'tool.result' }>['artifacts'][number],
): Artifact {
  return {
    artifactId: raw.artifact_id,
    kind: raw.kind,
    mimeType: raw.mime_type,
    data: raw.data,
    encoding: raw.encoding,
    title: raw.title,
    description: raw.description,
  }
}

function updateTurn(turns: Turn[], turnId: string, updater: (turn: Turn) => Turn): Turn[] {
  return turns.map((turn) => (turn.id === turnId ? updater(turn) : turn))
}

export function applyServerEvent(state: ChatStateSlice, msg: ServerEvent): Partial<ChatStateSlice> {
  switch (msg.type) {
    case 'session.started': {
      const toolCatalog = Object.fromEntries(msg.tools.map((tool) => [tool.name, tool])) as Record<string, ToolMeta>
      const next: Partial<ChatStateSlice> = {
        sessionId: msg.session_id,
        toolCatalog,
        // Block user input immediately so the pending turn can't flush before
        // the greeting run.started arrives and creates the greeting Turn.
        isStreaming: msg.has_greeting === true,
      }
      // Backend is the single source of truth for which models are actually used.
      // Overwrite whatever is in the store so the UI never shows a stale value.
      if (msg.agent_models) {
        next.agentModels = msg.agent_models
      }
      return next
    }

    case 'run.started': {
      // Greeting turn: created by the backend before any user message.
      // We synthesise a Turn on the fly since the user never called sendMessage.
      // isStreaming is already true from session.started's has_greeting flag.
      if (msg.is_greeting) {
        const greetingTurn: Turn = {
          id: msg.turn_id,
          userMessage: '',
          runId: msg.run_id,
          steps: [],
          artifacts: [],
          isGreeting: true,
          status: 'thinking',
          startedAt: Date.now(),
        }
        return { turns: [...state.turns, greetingTurn] }
      }
      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
          ...turn,
          runId: msg.run_id,
          startedAt: Date.now(),
        })),
        isStreaming: true,
      }
    }

    case 'assistant.message':
      // Manager synthesis → finalAnswer (rendered as Markdown in main bubble).
      // Streaming: each TextEvent is a chunk — append to build the full answer.
      // Specialist internal reports are suppressed — they are agent-to-agent
      // communication whose substance is re-stated by the Manager summary.
      if (msg.sender === 'Manager') {
        return {
          turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
            ...turn,
            finalAnswer: (turn.finalAnswer ?? '') + msg.message,
          })),
        }
      }
      // Swallow specialist intermediate replies silently
      return {}

    case 'tool.call': {
      const step: Step = {
        kind: 'tool_call',
        callId: msg.tool_call_id,
        tool: msg.tool.name,
        args: msg.arguments,
        sender: msg.sender,
        loadStatus: 'pending',
      }
      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
          ...turn,
          steps: [...turn.steps, step],
        })),
      }
    }

    case 'tool.result': {
      const artifacts = msg.artifacts.map(normalizeArtifact)
      // Merge result into the matching tool_call step (Action Grouping)
      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
          ...turn,
          steps: turn.steps.map((s) =>
            s.kind === 'tool_call' && s.callId === msg.tool_call_id
              ? {
                  ...s,
                  loadStatus: msg.status === 'success' ? 'success' : 'error',
                  summary: msg.summary,
                  retryHint: msg.retry_hint,
                  artifacts,
                  data: msg.data,
                }
              : s,
          ),
          artifacts: [...turn.artifacts, ...artifacts],
        })),
      }
    }

    case 'run.finished':
      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
          ...turn,
          status: 'done',
          finishedAt: Date.now(),
        })),
        isStreaming: false,
      }

    case 'run.failed':
      if (!msg.turn_id) {
        return { isStreaming: false }
      }

      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
          ...turn,
          status: 'done',
          finishedAt: Date.now(),
          steps: [...turn.steps, { kind: 'error', content: msg.error }],
        })),
        isStreaming: false,
      }

    case 'turn.status':
      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
          ...turn,
          statusMessage: msg.message,
        })),
      }

    default:
      return {}
  }
}

export function applySocketClosed(turns: Turn[]): Pick<ChatStateSlice, 'turns' | 'isStreaming'> {
  const activeTurn = [...turns].reverse().find((turn) => turn.status === 'thinking')
  if (!activeTurn) {
    return { turns, isStreaming: false }
  }

  return {
    turns: updateTurn(turns, activeTurn.id, (turn) => ({
      ...turn,
      status: 'done',
      finishedAt: Date.now(),
      steps: turn.steps.length
        ? turn.steps
        : [...turn.steps, { kind: 'error', content: '[System] Connection closed unexpectedly.' }],
    })),
    isStreaming: false,
  }
}

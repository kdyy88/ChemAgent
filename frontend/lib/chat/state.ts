import type { Artifact, ServerEvent, Step, ToolMeta, Turn } from '@/lib/types'

export type PendingTurn = {
  turnId: string
  prompt: string
}

export type ChatStateSlice = {
  sessionId: string | null
  turns: Turn[]
  isStreaming: boolean
  toolCatalog: Record<string, ToolMeta>
}

function createTurnId(): string {
  const cryptoApi = globalThis.crypto

  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID()
  }

  if (cryptoApi && typeof cryptoApi.getRandomValues === 'function') {
    const bytes = cryptoApi.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0'))
    return [
      hex.slice(0, 4).join(''),
      hex.slice(4, 6).join(''),
      hex.slice(6, 8).join(''),
      hex.slice(8, 10).join(''),
      hex.slice(10, 16).join(''),
    ].join('-')
  }

  return `turn_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`
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
      return { sessionId: msg.session_id, toolCatalog }
    }

    case 'run.started':
      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
          ...turn,
          runId: msg.run_id,
          startedAt: Date.now(),
        })),
        isStreaming: true,
      }

    case 'assistant.message':
      if (msg.sender === 'Manager') {
        return {
          turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
            ...turn,
            finalAnswer: msg.message,
          })),
        }
      }

      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
          ...turn,
          steps: [...turn.steps, { kind: 'agent_reply', content: msg.message, sender: msg.sender }],
        })),
      }

    case 'tool.call': {
      const step: Step = {
        kind: 'tool_call',
        callId: msg.tool_call_id,
        tool: msg.tool.name,
        args: msg.arguments,
        sender: msg.sender,
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
      const step: Step = {
        kind: 'tool_result',
        callId: msg.tool_call_id,
        tool: msg.tool.name,
        status: msg.status,
        summary: msg.summary,
        data: msg.data,
        retryHint: msg.retry_hint,
        artifacts,
        sender: msg.sender,
      }

      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
          ...turn,
          steps: [...turn.steps, step],
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

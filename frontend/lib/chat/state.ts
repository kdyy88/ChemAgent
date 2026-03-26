import type { Artifact, AgentModelConfig, ServerEvent, Step, ToolMeta, Turn, TurnStatus } from '@/lib/types'

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
  autoApprove: boolean
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

    case 'assistant.delta':
      // Token-by-token streaming chunk — goes into draftAnswer (shown live).
      // When the LLM turn finishes, assistant.message will set finalAnswer
      // and clear draftAnswer (replaced by the clean canonical version).
      if (msg.sender === 'Manager') {
        return {
          turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
            ...turn,
            draftAnswer: (turn.draftAnswer ?? '') + msg.content,
          })),
        }
      }
      return {}

    case 'assistant.message':
      // Clean complete text for one LLM turn — appends to finalAnswer and
      // clears draftAnswer (the raw streaming buffer that may contain XML tags).
      if (msg.sender === 'Manager') {
        return {
          turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
            ...turn,
            finalAnswer: (turn.finalAnswer ?? '') + msg.message,
            draftAnswer: undefined,  // clear raw streaming buffer
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

    // ── HITL events ──────────────────────────────────────────────────────

    case 'plan.proposed':
      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
          ...turn,
          steps: [...turn.steps, { kind: 'plan' as const, plan: msg.plan }],
        })),
      }

    case 'plan.status':
      if (msg.status === 'awaiting_approval') {
        return {
          turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
            ...turn,
            status: 'awaiting_approval' as const,
            statusMessage: '等待批准执行计划…',
          })),
          // Stop blocking input so the user can click approve/reject
          isStreaming: false,
        }
      }
      if (msg.status === 'rejected') {
        return {
          turns: updateTurn(state.turns, msg.turn_id, (turn) => ({
            ...turn,
            status: 'done' as const,
            statusMessage: '计划已拒绝',
            finishedAt: Date.now(),
          })),
          isStreaming: false,
        }
      }
      return {}

    case 'todo.progress':
      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => {
          // Replace the last todo step (if any) so the checklist updates
          // in-place instead of spawning duplicate entries.
          const lastTodoIdx = turn.steps.findLastIndex((s) => s.kind === 'todo')
          if (lastTodoIdx >= 0) {
            const newSteps = [...turn.steps]
            newSteps[lastTodoIdx] = { kind: 'todo' as const, todo: msg.todo }
            return { ...turn, steps: newSteps }
          }
          return { ...turn, steps: [...turn.steps, { kind: 'todo' as const, todo: msg.todo }] }
        }),
      }

    case 'thinking.delta':
      return {
        turns: updateTurn(state.turns, msg.turn_id, (turn) => {
          // Append content to the last thinking step, or create a new one
          const lastThinkIdx = turn.steps.findLastIndex((s) => s.kind === 'thinking')
          if (lastThinkIdx >= 0) {
            const newSteps = [...turn.steps]
            const existing = newSteps[lastThinkIdx] as Extract<Step, { kind: 'thinking' }>
            newSteps[lastThinkIdx] = { kind: 'thinking' as const, content: existing.content + msg.content }
            return { ...turn, steps: newSteps }
          }
          return { ...turn, steps: [...turn.steps, { kind: 'thinking' as const, content: msg.content }] }
        }),
      }

    case 'state.snapshot': {
      // Reconnect replay — reconstruct a Turn from the server snapshot
      const snapshotTurnId = msg.turn_id
      if (!snapshotTurnId) return {}
      // Skip if a turn with this ID already exists (avoid duplicates)
      if (state.turns.some((t) => t.id === snapshotTurnId)) return {}

      const snapshotSteps: Step[] = []
      if (msg.last_plan) {
        snapshotSteps.push({ kind: 'plan' as const, plan: msg.last_plan })
      }
      if (msg.last_todo) {
        snapshotSteps.push({ kind: 'todo' as const, todo: msg.last_todo })
      }

      const snapshotStatus: TurnStatus =
        msg.state === 'awaiting_approval' ? 'awaiting_approval' : 'done'

      const restoredTurn: Turn = {
        id: snapshotTurnId,
        userMessage: '',
        runId: msg.run_id || undefined,
        steps: snapshotSteps,
        artifacts: [],
        finalAnswer: msg.last_answer || undefined,
        status: snapshotStatus,
        statusMessage: '会话已恢复',
        startedAt: Date.now(),
        finishedAt: snapshotStatus === 'done' ? Date.now() : undefined,
      }

      return {
        turns: [...state.turns, restoredTurn],
        isStreaming: snapshotStatus === 'awaiting_approval' ? false : state.isStreaming,
      }
    }

    case 'settings.updated':
      return { autoApprove: msg.auto_approve }

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

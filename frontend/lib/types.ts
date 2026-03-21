export type TurnStatus = 'thinking' | 'done'

/** Per-agent model assignments sent from the frontend and echoed back by the backend. */
export type AgentModelConfig = {
  manager?: string
  visualizer?: string
  researcher?: string
  analyst?: string
}

export type Artifact = {
  artifactId: string
  kind: string
  mimeType: string
  data: string | Record<string, unknown> | unknown[]
  encoding: 'base64' | 'utf8' | 'json'
  title?: string | null
  description?: string | null
}

export type ToolMeta = {
  name: string
  description: string
  displayName: string
  category: string
  outputKinds: string[]
  tags: string[]
}

export type Step =
  | {
      kind: 'tool_call'
      callId: string
      tool: string
      args: Record<string, unknown>
      sender?: string
      // Merged result — filled when the matching tool.result arrives
      loadStatus: 'pending' | 'success' | 'error'
      summary?: string
      retryHint?: string
      artifacts?: Artifact[]
      data?: unknown
    }
  | {
      kind: 'tool_result'
      callId?: string
      tool: string
      status: 'success' | 'error'
      summary: string
      data: Record<string, unknown>
      retryHint?: string
      artifacts: Artifact[]
      sender?: string
    }
  | { kind: 'agent_reply'; content: string; sender?: string }
  | { kind: 'error'; content: string }

export type Turn = {
  id: string
  userMessage: string
  runId?: string
  steps: Step[]
  artifacts: Artifact[]
  // Manager's final synthesised answer — rendered as Markdown in the main bubble.
  // Kept separate from steps so the ThinkingLog shows Specialist work only.
  finalAnswer?: string
  status: TurnStatus
  // Live status label sent by the backend (e.g. "正在分析请求…", "正在连接专家…")
  statusMessage?: string
  /** True for the auto-generated greeting turn — no user bubble is shown. */
  isGreeting?: boolean
  startedAt: number
  finishedAt?: number
}

export type ServerEvent =
  | { type: 'session.started'; session_id: string; tools: ToolMeta[]; resumed: boolean; has_greeting?: boolean; agent_models?: AgentModelConfig }
  | { type: 'run.started'; session_id: string; turn_id: string; run_id: string; prompt: string; is_greeting?: boolean }
  | { type: 'assistant.message'; session_id: string; turn_id: string; run_id: string; message: string; sender?: string }
  | {
      type: 'tool.call'
      session_id: string
      turn_id: string
      run_id: string
      tool_call_id: string
      tool: { name: string }
      arguments: Record<string, unknown>
      sender?: string
    }
  | {
      type: 'tool.result'
      session_id: string
      turn_id: string
      run_id: string
      tool_call_id?: string
      tool: { name: string }
      status: 'success' | 'error'
      summary: string
      data: Record<string, unknown>
      retry_hint?: string
      error_code?: string
      sender?: string
      artifacts: Array<{
        artifact_id: string
        kind: string
        mime_type: string
        data: string | Record<string, unknown> | unknown[]
        encoding: 'base64' | 'utf8' | 'json'
        title?: string | null
        description?: string | null
      }>
    }
  | {
      type: 'run.finished'
      session_id: string
      turn_id: string
      run_id: string
      summary?: string | null
      last_speaker?: string | null
    }
  | { type: 'run.failed'; session_id?: string; turn_id?: string; run_id?: string; error: string }
  | { type: 'turn.status'; session_id: string; turn_id: string; run_id?: string; phase: string; message: string }

export type ClientEvent =
  | { type: 'session.start'; agent_models?: AgentModelConfig }
  | { type: 'session.resume'; session_id: string }
  | { type: 'session.clear'; content: ''; agent_models?: AgentModelConfig }
  | { type: 'user.message'; turn_id: string; content: string }

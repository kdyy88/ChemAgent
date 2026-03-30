// ── Artifact payloads ────────────────────────────────────────────────────────

export interface MoleculeImageArtifact {
  type: 'artifact'
  kind: 'molecule_image' | 'descriptor_structure_image' | 'highlighted_substructure'
  session_id: string
  turn_id: string
  title: string
  smiles?: string
  image: string
  highlight_atoms?: number[]
  match_atoms?: number[][]
}

export interface ConformerSdfArtifact {
  type: 'artifact'
  kind: 'conformer_sdf'
  session_id: string
  turn_id: string
  title: string
  smiles?: string
  sdf_content: string
  energy?: number
}

export interface PdbqtFileArtifact {
  type: 'artifact'
  kind: 'pdbqt_file'
  session_id: string
  turn_id: string
  title: string
  smiles?: string
  pdbqt_content: string
  rotatable_bonds?: number
}

export interface FormatConversionArtifact {
  type: 'artifact'
  kind: 'format_conversion'
  session_id: string
  turn_id: string
  title: string
  input_format?: string
  output_format?: string
  output: string
}

export type SSEArtifactEvent =
  | MoleculeImageArtifact
  | ConformerSdfArtifact
  | PdbqtFileArtifact
  | FormatConversionArtifact


export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export interface SSETaskItem {
  id: string
  description: string
  status: TaskStatus
}


// ── SSE event union ───────────────────────────────────────────────────────────

/** Fired immediately when the POST is accepted and the graph begins. */
export interface SSERunStarted {
  type: 'run_started'
  session_id: string
  turn_id: string
  message: string
}

/** Fired when a named LangGraph node begins execution. */
export interface SSENodeStart {
  type: 'node_start'
  node: 'task_router' | 'planner_node' | 'chem_agent' | 'tools_executor'
  session_id: string
  turn_id: string
}

/** Fired when a named LangGraph node finishes execution. */
export interface SSENodeEnd {
  type: 'node_end'
  node: 'task_router' | 'planner_node' | 'chem_agent' | 'tools_executor'
  session_id: string
  turn_id: string
}

export interface SSETaskUpdate {
  type: 'task_update'
  tasks: SSETaskItem[]
  source?: string
  session_id: string
  turn_id: string
}

/** A single streaming token from an LLM node — use for typewriter UX. */
export interface SSEToken {
  type: 'token'
  node: string
  session_id: string
  turn_id: string
  content: string       // partial text — append to the current bubble
}

/** An RDKit @tool started running (show spinner in ThinkingLog). */
export interface SSEToolStart {
  type: 'tool_start'
  tool: string
  input: Record<string, unknown>
  session_id: string
  turn_id: string
}

/** An RDKit @tool finished — may contain parsed JSON result. */
export interface SSEToolEnd {
  type: 'tool_end'
  tool: string
  output: Record<string, unknown> | string
  session_id: string
  turn_id: string
}

/** Shadow Lab detected an invalid SMILES — triggers self-correction loop. */
export interface SSEShadowError {
  type: 'shadow_error'
  smiles: string | null
  error: string
  session_id: string
  turn_id: string
}

/** Researcher paused to ask the user a clarifying question (Human-in-the-Loop). */
export interface SSEInterrupt {
  type: 'interrupt'
  /** The clarifying question for the user (Chinese). */
  question: string
  /** Quick-reply option labels (2-4 items, Chinese). */
  options: string[]
  /** Tools already called before the pause. */
  called_tools: string[]
  /** Opaque ID for correlation. */
  interrupt_id: string
  known_smiles?: string
  session_id: string
  turn_id: string
}

/** Researcher intermediate reasoning step — emitted before each tool call batch. */
export interface SSEThinking {
  type: 'thinking'
  text: string
  iteration: number
  done?: boolean
  source?: string
  category?: 'node' | 'tool' | 'llm' | 'status' | 'error'
  importance?: 'high' | 'low'
  group_key?: string
  session_id: string
  turn_id: string
}

/** Final event — the graph run completed successfully. */
export interface SSEDone {
  type: 'done'
  session_id: string
  turn_id: string
  checkpoint_id?: string
}

/** Unhandled exception — stream terminates after this. */
export interface SSEError {
  type: 'error'
  error: string
  traceback?: string
  session_id: string
  turn_id: string
}

export interface InterruptContext {
  interrupt_id: string
}

export interface SSESendMessageOptions {
  activeSmiles?: string | null
  interruptContext?: InterruptContext
}

export interface SSEToolCall {
  tool: string
  input: Record<string, unknown>
  output?: Record<string, unknown>
  done: boolean
}

export interface SSEPendingInterrupt {
  question: string
  options: string[]
  called_tools: string[]
  interrupt_id: string
  known_smiles?: string
}

export type SSEEvent =
  | SSERunStarted
  | SSENodeStart
  | SSENodeEnd
  | SSEToken
  | SSEToolStart
  | SSEToolEnd
  | SSEArtifactEvent
  | SSETaskUpdate
  | SSEShadowError
  | SSEInterrupt
  | SSEThinking
  | SSEDone
  | SSEError


// ── Local UI state produced by the hook ───────────────────────────────────────

export type NodeStatus = 'idle' | 'running' | 'done'

export interface SSETurn {
  turnId: string
  userMessage: string
  /** Streaming / final assistant answer (assembled from token events). */
  assistantText: string
  /** Is the stream still active? */
  isStreaming: boolean
  /** Currently executing node, if any. */
  activeNode: string | null
  /** All tools called so far in this turn. */
  toolCalls: SSEToolCall[]
  /** Rich artifacts (images, descriptor tables). */
  artifacts: SSEArtifactEvent[]
  /** Planner-generated tasks and their live execution states. */
  tasks: SSETaskItem[]
  /** Shadow Lab errors to surface in UI. */
  shadowErrors: SSEShadowError[]
  /** Human-readable status label (e.g. "analyst 分析中…"). */
  statusLabel: string
  /** Set when researcher pauses for user clarification (HITL). Cleared on next send. */
  pendingInterrupt?: SSEPendingInterrupt
  /** Unified reasoning stream shown in the chain-of-thought area. */
  thinkingSteps: SSEThinking[]
}

/**
 * SSE event types for the LangGraph /api/chat/stream endpoint.
 *
 * These types mirror the JSON payloads emitted by backend/app/api/sse_chat.py.
 * The discriminator field is always `type`.
 *
 * Artifact kinds emitted by worker nodes:
 *   - "molecule_image"  : base64-encoded PNG (2D structure)
 *   - "descriptors"     : JSON object with Lipinski / QED / … data
 */

// ── Artifact (rich media from worker nodes) ───────────────────────────────────

export interface MoleculeImageArtifact {
  kind: 'molecule_image'
  mime_type: 'image/png'
  encoding: 'base64'
  data: string          // bare base64 PNG — prepend "data:image/png;base64," in JSX
  smiles: string
  title: string
}

export interface DescriptorsArtifact {
  kind: 'descriptors'
  mime_type: 'application/json'
  encoding: 'json'
  data: {
    smiles?: string
    name?: string
    formula?: string
    descriptors?: {
      molecular_weight: number
      log_p: number
      h_bond_donors: number
      h_bond_acceptors: number
      tpsa: number
      qed: number
      sa_score: number
      rotatable_bonds: number
      ring_count: number
      aromatic_rings: number
      fraction_csp3: number
      heavy_atom_count: number
    }
    lipinski?: {
      pass: boolean
      violations: number
    }
    [key: string]: unknown
  }
  title: string
}

export type SSEArtifact = MoleculeImageArtifact | DescriptorsArtifact


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
  node: 'supervisor' | 'visualizer' | 'analyst' | 'shadow_lab'
  session_id: string
  turn_id: string
}

/** Fired when a named LangGraph node finishes execution. */
export interface SSENodeEnd {
  type: 'node_end'
  node: 'supervisor' | 'visualizer' | 'analyst' | 'shadow_lab'
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

/** A rich artifact emitted by a worker node (image or descriptor table). */
export interface SSEArtifactEvent extends SSEArtifact {
  type: 'artifact'
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

/** Final event — the graph run completed successfully. */
export interface SSEDone {
  type: 'done'
  session_id: string
  turn_id: string
}

/** Unhandled exception — stream terminates after this. */
export interface SSEError {
  type: 'error'
  error: string
  traceback?: string
  session_id: string
  turn_id: string
}

export type SSEEvent =
  | SSERunStarted
  | SSENodeStart
  | SSENodeEnd
  | SSEToken
  | SSEToolStart
  | SSEToolEnd
  | SSEArtifactEvent
  | SSEShadowError
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
  toolCalls: Array<{ tool: string; input: Record<string, unknown>; done: boolean }>
  /** Rich artifacts (images, descriptor tables). */
  artifacts: SSEArtifactEvent[]
  /** Shadow Lab errors to surface in UI. */
  shadowErrors: SSEShadowError[]
  /** Human-readable status label (e.g. "analyst 分析中…"). */
  statusLabel: string
}

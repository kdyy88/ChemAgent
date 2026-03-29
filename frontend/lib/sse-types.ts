/**
 * SSE event types for the LangGraph /api/chat/stream endpoint.
 *
 * These types mirror the JSON payloads emitted by backend/app/api/sse_chat.py.
 * The discriminator field is always `type`.
 *
 * Artifact kinds emitted by worker nodes:
 *   - "structure_image"   : base64-encoded PNG (2D structure, visualizer node)
 *   - "descriptors"       : JSON object with Lipinski / QED / … data (analyst node)
 *   - "conformer_3d"      : SDF text of force-field-optimised 3D conformer (prep node)
 *   - "pdbqt"             : PDBQT string for AutoDock/Vina/Smina docking (prep node)
 *   - "format_conversion" : Converted molecule string (prep node)
 */

// ── Artifact (rich media from worker nodes) ───────────────────────────────────

export interface StructureImageArtifact {
  kind: 'structure_image'
  mime_type: 'image/png'
  encoding: 'base64'
  data: string          // bare base64 PNG — prepend "data:image/png;base64," in JSX
  smiles: string
  title: string
}

/** @deprecated use StructureImageArtifact — kept for backward compat */
export interface MoleculeImageArtifact {
  kind: 'molecule_image'
  mime_type: 'image/png'
  encoding: 'base64'
  data: string
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

export interface Conformer3DArtifact {
  kind: 'conformer_3d'
  mime_type: 'chemical/x-mdl-sdfile'
  encoding: 'utf8'
  data: string          // SDF text content
  title: string
  energy_kcal_mol?: number
  forcefield?: string
}

export interface PdbqtArtifact {
  kind: 'pdbqt'
  mime_type: 'chemical/x-pdbqt'
  encoding: 'utf8'
  data: string          // PDBQT text content
  title: string
  rotatable_bonds?: number
}

export interface FormatConversionArtifact {
  kind: 'format_conversion'
  mime_type: string     // varies: 'chemical/x-mdl-sdfile', 'chemical/x-mol2', etc.
  encoding: 'utf8'
  data: string          // converted molecule string
  title: string
  input_fmt?: string
  output_fmt?: string
}

export type SSEArtifact =
  | StructureImageArtifact
  | MoleculeImageArtifact
  | DescriptorsArtifact
  | Conformer3DArtifact
  | PdbqtArtifact
  | FormatConversionArtifact


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
  node: 'supervisor' | 'responder' | 'researcher' | 'visualizer' | 'analyst' | 'prep' | 'shadow_lab'
  session_id: string
  turn_id: string
}

/** Fired when a named LangGraph node finishes execution. */
export interface SSENodeEnd {
  type: 'node_end'
  node: 'supervisor' | 'responder' | 'researcher' | 'visualizer' | 'analyst' | 'prep' | 'shadow_lab'
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

/** A rich artifact emitted by a worker node (image or descriptor table).
 *  Typed as a distributed union so TypeScript can narrow on `artifact.kind`.
 */
export type SSEArtifactEvent =
  | (StructureImageArtifact  & { type: 'artifact'; session_id: string; turn_id: string })
  | (MoleculeImageArtifact   & { type: 'artifact'; session_id: string; turn_id: string })
  | (DescriptorsArtifact     & { type: 'artifact'; session_id: string; turn_id: string })
  | (Conformer3DArtifact     & { type: 'artifact'; session_id: string; turn_id: string })
  | (PdbqtArtifact           & { type: 'artifact'; session_id: string; turn_id: string })
  | (FormatConversionArtifact & { type: 'artifact'; session_id: string; turn_id: string })

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
  session_id: string
  turn_id: string
}

/** Researcher intermediate reasoning step — emitted before each tool call batch. */
export interface SSEThinking {
  type: 'thinking'
  text: string
  iteration: number
  /** false = still streaming this step; true = step complete. */
  done?: boolean
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
  toolCalls: Array<{ tool: string; input: Record<string, unknown>; output?: Record<string, unknown>; done: boolean }>
  /** Rich artifacts (images, descriptor tables). */
  artifacts: SSEArtifactEvent[]
  /** Shadow Lab errors to surface in UI. */
  shadowErrors: SSEShadowError[]
  /** Human-readable status label (e.g. "analyst 分析中…"). */
  statusLabel: string
  /** Set when researcher pauses for user clarification (HITL). Cleared on next send. */
  pendingInterrupt?: {
    question: string
    options: string[]
    called_tools: string[]
    interrupt_id: string
    known_smiles?: string
  }
  /** Intermediate reasoning steps captured before tool calls (inner monologue). */
  thinkingSteps: SSEThinking[]
}

import { describe, it, expect } from 'vitest'
import { createTurn, applyServerEvent, applySocketClosed, type ChatStateSlice } from '../state'
import type { Turn, ServerEvent } from '@/lib/types'

// ── Fixtures ───────────────────────────────────────────────────────────────────

function makeTurn(overrides: Partial<Turn> = {}): Turn {
  return {
    id: 'turn-1',
    userMessage: 'Hello',
    steps: [],
    artifacts: [],
    status: 'thinking',
    startedAt: 0,
    ...overrides,
  }
}

function makeState(overrides: Partial<ChatStateSlice> = {}): ChatStateSlice {
  return {
    sessionId: null,
    turns: [],
    isStreaming: false,
    toolCatalog: {},
    agentModels: {},
    ...overrides,
  }
}

// ── createTurn ─────────────────────────────────────────────────────────────────

describe('createTurn()', () => {
  it('sets userMessage from prompt', () => {
    const turn = createTurn('What is aspirin?')
    expect(turn.userMessage).toBe('What is aspirin?')
  })

  it('initial status is "thinking"', () => {
    expect(createTurn('test').status).toBe('thinking')
  })

  it('starts with empty steps and artifacts', () => {
    const turn = createTurn('test')
    expect(turn.steps).toEqual([])
    expect(turn.artifacts).toEqual([])
  })

  it('assigns a non-empty id', () => {
    const turn = createTurn('test')
    expect(turn.id).toBeTruthy()
    expect(typeof turn.id).toBe('string')
  })

  it('each turn gets a unique id', () => {
    const ids = new Set(Array.from({ length: 20 }, () => createTurn('x').id))
    expect(ids.size).toBe(20)
  })

  it('startedAt is 0 initially', () => {
    expect(createTurn('test').startedAt).toBe(0)
  })
})

// ── applyServerEvent – session.started ────────────────────────────────────────

describe('applyServerEvent – session.started', () => {
  const baseMsg: ServerEvent = {
    type: 'session.started',
    session_id: 'sess-001',
    tools: [
      { name: 'validate_smiles', description: 'validates', displayName: 'Validate', category: 'rdkit', outputKinds: [], tags: [] },
    ],
    resumed: false,
  }

  it('sets sessionId', () => {
    const result = applyServerEvent(makeState(), baseMsg)
    expect(result.sessionId).toBe('sess-001')
  })

  it('builds toolCatalog from tools array', () => {
    const result = applyServerEvent(makeState(), baseMsg)
    expect(result.toolCatalog?.validate_smiles).toBeDefined()
    expect(result.toolCatalog?.validate_smiles.displayName).toBe('Validate')
  })

  it('sets isStreaming=false when has_greeting is absent', () => {
    const result = applyServerEvent(makeState(), baseMsg)
    expect(result.isStreaming).toBe(false)
  })

  it('sets isStreaming=true when has_greeting=true', () => {
    const msg = { ...baseMsg, has_greeting: true }
    const result = applyServerEvent(makeState(), msg)
    expect(result.isStreaming).toBe(true)
  })

  it('sets agentModels when provided', () => {
    const msg = { ...baseMsg, agent_models: { manager: 'gpt-4o', visualizer: 'gpt-4o-mini' } }
    const result = applyServerEvent(makeState(), msg)
    expect(result.agentModels).toEqual({ manager: 'gpt-4o', visualizer: 'gpt-4o-mini' })
  })

  it('does not set agentModels when not provided', () => {
    const result = applyServerEvent(makeState(), baseMsg)
    expect(result.agentModels).toBeUndefined()
  })
})

// ── applyServerEvent – run.started ────────────────────────────────────────────

describe('applyServerEvent – run.started (greeting)', () => {
  const greetingMsg: ServerEvent = {
    type: 'run.started',
    session_id: 'sess-001',
    turn_id: 'greet-turn',
    run_id: 'run-greet',
    prompt: '',
    is_greeting: true,
  }

  it('appends a new greeting turn to state.turns', () => {
    const state = makeState()
    const result = applyServerEvent(state, greetingMsg)
    expect(result.turns).toHaveLength(1)
    expect(result.turns![0].id).toBe('greet-turn')
    expect(result.turns![0].isGreeting).toBe(true)
  })

  it('greeting turn has thinking status', () => {
    const result = applyServerEvent(makeState(), greetingMsg)
    expect(result.turns![0].status).toBe('thinking')
  })

  it('does not change isStreaming on greeting run.started', () => {
    const result = applyServerEvent(makeState(), greetingMsg)
    expect(result.isStreaming).toBeUndefined()
  })
})

describe('applyServerEvent – run.started (normal)', () => {
  const normalMsg: ServerEvent = {
    type: 'run.started',
    session_id: 'sess-001',
    turn_id: 'turn-1',
    run_id: 'run-001',
    prompt: 'test',
  }

  it('patches runId and startedAt onto the existing turn', () => {
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' })] })
    const result = applyServerEvent(state, normalMsg)
    const turn = result.turns!.find((t) => t.id === 'turn-1')!
    expect(turn.runId).toBe('run-001')
    expect(turn.startedAt).toBeGreaterThan(0)
  })

  it('sets isStreaming=true', () => {
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' })] })
    const result = applyServerEvent(state, normalMsg)
    expect(result.isStreaming).toBe(true)
  })

  it('does not touch other turns', () => {
    const otherTurn = makeTurn({ id: 'turn-2', status: 'done' })
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' }), otherTurn] })
    const result = applyServerEvent(state, normalMsg)
    expect(result.turns!.find((t) => t.id === 'turn-2')).toEqual(otherTurn)
  })
})

// ── applyServerEvent – assistant.message ──────────────────────────────────────

describe('applyServerEvent – assistant.message', () => {
  const turn = makeTurn({ id: 'turn-1', finalAnswer: undefined })
  const state = makeState({ turns: [turn] })

  it('appends message to finalAnswer when sender is Manager', () => {
    const msg: ServerEvent = {
      type: 'assistant.message',
      session_id: 'sess',
      turn_id: 'turn-1',
      run_id: 'run-1',
      message: 'Hello from Manager',
      sender: 'Manager',
    }
    const result = applyServerEvent(state, msg)
    expect(result.turns![0].finalAnswer).toBe('Hello from Manager')
  })

  it('concatenates multiple Manager messages', () => {
    const state2 = makeState({ turns: [makeTurn({ id: 'turn-1', finalAnswer: 'Part 1 ' })] })
    const msg: ServerEvent = {
      type: 'assistant.message',
      session_id: 'sess',
      turn_id: 'turn-1',
      run_id: 'run-1',
      message: 'Part 2',
      sender: 'Manager',
    }
    const result = applyServerEvent(state2, msg)
    expect(result.turns![0].finalAnswer).toBe('Part 1 Part 2')
  })

  it('returns empty object for non-Manager sender', () => {
    const msg: ServerEvent = {
      type: 'assistant.message',
      session_id: 'sess',
      turn_id: 'turn-1',
      run_id: 'run-1',
      message: 'Specialist reply',
      sender: 'Researcher',
    }
    const result = applyServerEvent(state, msg)
    expect(result).toEqual({})
  })

  it('returns empty object when sender is undefined', () => {
    const msg: ServerEvent = {
      type: 'assistant.message',
      session_id: 'sess',
      turn_id: 'turn-1',
      run_id: 'run-1',
      message: 'No sender',
    }
    const result = applyServerEvent(state, msg)
    expect(result).toEqual({})
  })
})

// ── applyServerEvent – tool.call ──────────────────────────────────────────────

describe('applyServerEvent – tool.call', () => {
  it('appends a pending tool_call step', () => {
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' })] })
    const msg: ServerEvent = {
      type: 'tool.call',
      session_id: 'sess',
      turn_id: 'turn-1',
      run_id: 'run-1',
      tool_call_id: 'call-42',
      tool: { name: 'validate_smiles' },
      arguments: { smiles: 'CCO' },
      sender: 'Visualizer',
    }
    const result = applyServerEvent(state, msg)
    const step = result.turns![0].steps[0]
    expect(step.kind).toBe('tool_call')
    if (step.kind === 'tool_call') {
      expect(step.callId).toBe('call-42')
      expect(step.tool).toBe('validate_smiles')
      expect(step.loadStatus).toBe('pending')
      expect(step.args).toEqual({ smiles: 'CCO' })
      expect(step.sender).toBe('Visualizer')
    }
  })
})

// ── applyServerEvent – tool.result ────────────────────────────────────────────

describe('applyServerEvent – tool.result', () => {
  const turnWithStep = makeTurn({
    id: 'turn-1',
    steps: [
      { kind: 'tool_call', callId: 'call-42', tool: 'validate_smiles', args: {}, loadStatus: 'pending' },
    ],
  })

  const resultMsg: ServerEvent = {
    type: 'tool.result',
    session_id: 'sess',
    turn_id: 'turn-1',
    run_id: 'run-1',
    tool_call_id: 'call-42',
    tool: { name: 'validate_smiles' },
    status: 'success',
    summary: 'Valid SMILES',
    data: { is_valid: true },
    artifacts: [],
    sender: 'Visualizer',
  }

  it('sets loadStatus to success', () => {
    const state = makeState({ turns: [turnWithStep] })
    const result = applyServerEvent(state, resultMsg)
    const step = result.turns![0].steps[0]
    if (step.kind === 'tool_call') {
      expect(step.loadStatus).toBe('success')
    }
  })

  it('sets loadStatus to error on failure', () => {
    const failMsg: ServerEvent = { ...resultMsg, status: 'error' }
    const state = makeState({ turns: [turnWithStep] })
    const result = applyServerEvent(state, failMsg)
    const step = result.turns![0].steps[0]
    if (step.kind === 'tool_call') {
      expect(step.loadStatus).toBe('error')
    }
  })

  it('sets summary on the step', () => {
    const state = makeState({ turns: [turnWithStep] })
    const result = applyServerEvent(state, resultMsg)
    const step = result.turns![0].steps[0]
    if (step.kind === 'tool_call') {
      expect(step.summary).toBe('Valid SMILES')
    }
  })

  it('normalizes and merges artifacts into turn', () => {
    const msg: ServerEvent = {
      ...resultMsg,
      artifacts: [
        {
          artifact_id: 'art-1',
          kind: 'image',
          mime_type: 'image/png',
          data: 'base64data',
          encoding: 'base64',
          title: 'Structure',
          description: null,
        },
      ],
    }
    const state = makeState({ turns: [turnWithStep] })
    const result = applyServerEvent(state, msg)
    expect(result.turns![0].artifacts).toHaveLength(1)
    expect(result.turns![0].artifacts[0].artifactId).toBe('art-1')
    expect(result.turns![0].artifacts[0].mimeType).toBe('image/png')
  })

  it('does not update unmatched steps', () => {
    const otherStep = { kind: 'tool_call' as const, callId: 'call-99', tool: 'other', args: {}, loadStatus: 'pending' as const }
    const turnWithTwo = makeTurn({ id: 'turn-1', steps: [turnWithStep.steps[0], otherStep] })
    const state = makeState({ turns: [turnWithTwo] })
    const result = applyServerEvent(state, resultMsg)
    const steps = result.turns![0].steps
    const unmatched = steps.find((s) => s.kind === 'tool_call' && s.callId === 'call-99')
    if (unmatched?.kind === 'tool_call') {
      expect(unmatched.loadStatus).toBe('pending')
    }
  })
})

// ── applyServerEvent – run.finished ───────────────────────────────────────────

describe('applyServerEvent – run.finished', () => {
  it('sets status to done', () => {
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' })] })
    const msg: ServerEvent = {
      type: 'run.finished',
      session_id: 'sess',
      turn_id: 'turn-1',
      run_id: 'run-1',
    }
    const result = applyServerEvent(state, msg)
    expect(result.turns![0].status).toBe('done')
  })

  it('sets finishedAt timestamp', () => {
    const before = Date.now()
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' })] })
    const msg: ServerEvent = {
      type: 'run.finished',
      session_id: 'sess',
      turn_id: 'turn-1',
      run_id: 'run-1',
    }
    const result = applyServerEvent(state, msg)
    expect(result.turns![0].finishedAt).toBeGreaterThanOrEqual(before)
  })

  it('sets isStreaming=false', () => {
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' })] })
    const msg: ServerEvent = {
      type: 'run.finished',
      session_id: 'sess',
      turn_id: 'turn-1',
      run_id: 'run-1',
    }
    const result = applyServerEvent(state, msg)
    expect(result.isStreaming).toBe(false)
  })
})

// ── applyServerEvent – run.failed ─────────────────────────────────────────────

describe('applyServerEvent – run.failed', () => {
  it('returns only { isStreaming: false } when turn_id is absent', () => {
    const msg: ServerEvent = { type: 'run.failed', error: 'Server error' }
    const result = applyServerEvent(makeState(), msg)
    expect(result).toEqual({ isStreaming: false })
  })

  it('appends an error step when turn_id is present', () => {
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' })] })
    const msg: ServerEvent = {
      type: 'run.failed',
      turn_id: 'turn-1',
      error: 'Timeout',
    }
    const result = applyServerEvent(state, msg)
    const lastStep = result.turns![0].steps.at(-1)!
    expect(lastStep.kind).toBe('error')
    if (lastStep.kind === 'error') {
      expect(lastStep.content).toBe('Timeout')
    }
  })

  it('sets turn status to done', () => {
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' })] })
    const msg: ServerEvent = { type: 'run.failed', turn_id: 'turn-1', error: 'oops' }
    const result = applyServerEvent(state, msg)
    expect(result.turns![0].status).toBe('done')
  })

  it('sets isStreaming=false when turn_id is present', () => {
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' })] })
    const msg: ServerEvent = { type: 'run.failed', turn_id: 'turn-1', error: 'oops' }
    const result = applyServerEvent(state, msg)
    expect(result.isStreaming).toBe(false)
  })
})

// ── applyServerEvent – turn.status ────────────────────────────────────────────

describe('applyServerEvent – turn.status', () => {
  it('sets statusMessage on the matching turn', () => {
    const state = makeState({ turns: [makeTurn({ id: 'turn-1' })] })
    const msg: ServerEvent = {
      type: 'turn.status',
      session_id: 'sess',
      turn_id: 'turn-1',
      phase: 'tool_call',
      message: '正在连接专家…',
    }
    const result = applyServerEvent(state, msg)
    expect(result.turns![0].statusMessage).toBe('正在连接专家…')
  })
})

// ── applySocketClosed ──────────────────────────────────────────────────────────

describe('applySocketClosed()', () => {
  it('returns turns as-is with isStreaming=false when no turn is thinking', () => {
    const turns = [makeTurn({ id: 'turn-1', status: 'done' })]
    const result = applySocketClosed(turns)
    expect(result.isStreaming).toBe(false)
    expect(result.turns).toEqual(turns)
  })

  it('sets thinking turn to done', () => {
    const turns = [makeTurn({ id: 'turn-1', status: 'thinking', steps: [{ kind: 'tool_call', callId: 'c', tool: 't', args: {}, loadStatus: 'pending' }] })]
    const result = applySocketClosed(turns)
    expect(result.turns[0].status).toBe('done')
    expect(result.isStreaming).toBe(false)
  })

  it('keeps existing steps when thinking turn has steps', () => {
    const existingSteps = [{ kind: 'tool_call' as const, callId: 'c', tool: 't', args: {}, loadStatus: 'success' as const, summary: 'done' }]
    const turns = [makeTurn({ id: 'turn-1', status: 'thinking', steps: existingSteps })]
    const result = applySocketClosed(turns)
    expect(result.turns[0].steps).toHaveLength(1)
    expect(result.turns[0].steps[0].kind).toBe('tool_call')
  })

  it('injects a system error step when thinking turn has no steps', () => {
    const turns = [makeTurn({ id: 'turn-1', status: 'thinking', steps: [] })]
    const result = applySocketClosed(turns)
    expect(result.turns[0].steps).toHaveLength(1)
    const step = result.turns[0].steps[0]
    expect(step.kind).toBe('error')
    if (step.kind === 'error') {
      expect(step.content).toMatch(/Connection closed/i)
    }
  })

  it('only closes the most recent thinking turn (last-wins)', () => {
    const turns = [
      makeTurn({ id: 'turn-1', status: 'thinking', steps: [] }),
      makeTurn({ id: 'turn-2', status: 'thinking', steps: [] }),
    ]
    const result = applySocketClosed(turns)
    // Only turn-2 (the last thinking turn) should become done with injected step
    expect(result.turns.find((t) => t.id === 'turn-2')!.steps).toHaveLength(1)
    // turn-1 is not the most recent — applySocketClosed uses .reverse().find()
    // so turn-2 is found first; turn-1 is NOT updated
    expect(result.turns.find((t) => t.id === 'turn-1')!.status).toBe('thinking')
  })
})

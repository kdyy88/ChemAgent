import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ThinkingLog } from '../ThinkingLog'
import type { Step, TurnStatus } from '@/lib/types'

// ── Mock complex UI primitives ─────────────────────────────────────────────────
// These Radix-based components are not critical to what we want to test.
// We replace them with simple wrappers that render their children.

vi.mock('@/components/ui/chain-of-thought', () => ({
  ChainOfThought: ({ children }: { children: React.ReactNode }) => <div data-testid="cot">{children}</div>,
  ChainOfThoughtStep: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ChainOfThoughtTrigger: ({ children, leftIcon }: { children: React.ReactNode; leftIcon?: React.ReactNode }) => (
    <div data-testid="cot-trigger">{leftIcon}{children}</div>
  ),
  ChainOfThoughtContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ChainOfThoughtItem: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/components/ui/steps', () => ({
  Steps: ({ children, open }: { children: React.ReactNode; open: boolean }) => (
    <div data-testid="steps" data-open={open}>{children}</div>
  ),
  StepsTrigger: ({ children, leftIcon }: { children: React.ReactNode; leftIcon?: React.ReactNode }) => (
    <div data-testid="steps-trigger">{leftIcon}{children}</div>
  ),
  StepsContent: ({ children }: { children: React.ReactNode }) => <div data-testid="steps-content">{children}</div>,
}))

vi.mock('@/components/ui/source', () => ({
  Source: ({ children }: { children: React.ReactNode }) => <span data-testid="source">{children}</span>,
  SourceTrigger: ({ label }: { label?: string }) => <span>{label}</span>,
  SourceContent: ({ title }: { title: string }) => <span>{title}</span>,
}))

// ── Fixtures ───────────────────────────────────────────────────────────────────

function makeTool(overrides?: Partial<Extract<Step, { kind: 'tool_call' }>>): Step {
  return {
    kind: 'tool_call',
    callId: 'call-1',
    tool: 'web_search',
    args: { query: 'aspirin' },
    loadStatus: 'success',
    summary: 'Found 3 results',
    ...overrides,
  }
}

function makeError(content = 'Something went wrong'): Step {
  return { kind: 'error', content }
}

function renderThinkingLog(steps: Step[], status: TurnStatus = 'thinking', overrides?: {
  startedAt?: number
  finishedAt?: number
  statusMessage?: string
}) {
  return render(
    <ThinkingLog
      steps={steps}
      status={status}
      startedAt={overrides?.startedAt ?? 0}
      finishedAt={overrides?.finishedAt}
      statusMessage={overrides?.statusMessage}
    />
  )
}

// ── Empty steps ────────────────────────────────────────────────────────────────

describe('ThinkingLog – empty steps', () => {
  it('shows animated "正在连接专家…" when steps=[] and status=thinking', () => {
    const { container } = renderThinkingLog([], 'thinking')
    expect(container.textContent).toContain('正在连接专家')
  })

  it('uses custom statusMessage when provided', () => {
    renderThinkingLog([], 'thinking', { statusMessage: '正在分析请求…' })
    expect(screen.getByText('正在分析请求…')).toBeInTheDocument()
  })

  it('returns null (nothing rendered) when steps=[] and status=done', () => {
    const { container } = renderThinkingLog([], 'done')
    expect(container.firstChild).toBeNull()
  })
})

// ── Trigger label ──────────────────────────────────────────────────────────────

describe('ThinkingLog – trigger label', () => {
  it('shows "思考中" text when status=thinking and has steps', () => {
    renderThinkingLog([makeTool()], 'thinking')
    expect(screen.getByTestId('steps-trigger').textContent).toContain('思考中')
  })

  it('shows step count and elapsed time when status=done', () => {
    renderThinkingLog(
      [makeTool(), makeTool({ callId: 'call-2' })],
      'done',
      { startedAt: 1000, finishedAt: 3500 }
    )
    const trigger = screen.getByTestId('steps-trigger').textContent ?? ''
    expect(trigger).toContain('2')
    expect(trigger).toContain('2.5s')
  })

  it('shows "N 个步骤" without time when finishedAt is absent', () => {
    renderThinkingLog([makeTool()], 'done', { startedAt: 0 })
    const trigger = screen.getByTestId('steps-trigger').textContent ?? ''
    expect(trigger).toContain('1')
    expect(trigger).toContain('步骤')
    expect(trigger).not.toMatch(/\d+\.\ds/)
  })
})

// ── ToolStep rendering ─────────────────────────────────────────────────────────

describe('ThinkingLog – ToolStep semantic labels', () => {
  it('shows semantic action label for web_search (pending)', () => {
    const step = makeTool({ tool: 'web_search', args: { query: 'aspirin uses' }, loadStatus: 'pending' })
    renderThinkingLog([step], 'thinking')
    expect(screen.getByTestId('steps-content').textContent).toContain('正在查阅')
    expect(screen.getByTestId('steps-content').textContent).toContain('aspirin uses')
  })

  it('shows "找到 N 条结果" for a web_search result', () => {
    const step = makeTool({ tool: 'web_search', summary: 'Found 5 results for aspirin', loadStatus: 'success' })
    renderThinkingLog([step], 'done')
    expect(screen.getByTestId('steps-content').textContent).toContain('找到 5 条结果')
  })

  it('shows "分子性质计算完毕" for analyze_molecule_from_smiles result', () => {
    const step = makeTool({ tool: 'analyze_molecule_from_smiles', summary: '', loadStatus: 'success' })
    renderThinkingLog([step], 'done')
    expect(screen.getByTestId('steps-content').textContent).toContain('分子性质计算完毕')
  })

  it('shows "失败：" prefix for error loadStatus', () => {
    const step = makeTool({ loadStatus: 'error' })
    renderThinkingLog([step], 'done')
    expect(screen.getByTestId('steps-content').textContent).toContain('失败：')
  })
})

// ── ErrorStepRow rendering ─────────────────────────────────────────────────────

describe('ThinkingLog – error steps', () => {
  it('renders an error step with its content', () => {
    renderThinkingLog([makeError('Timeout exceeded')], 'done')
    expect(screen.getByText('Timeout exceeded')).toBeInTheDocument()
  })

  it('truncates long error content in trigger (>80 chars)', () => {
    const longError = 'A'.repeat(100)
    renderThinkingLog([makeError(longError)], 'done')
    // Should show "…" after 80 chars
    const triggerText = screen.getByTestId('steps-content').textContent ?? ''
    expect(triggerText).toContain('A'.repeat(80))
    expect(triggerText).toContain('…')
  })
})

// ── SenderBadge ───────────────────────────────────────────────────────────────

describe('ThinkingLog – SenderBadge', () => {
  it('shows sender badge for Manager', () => {
    const step = makeTool({ sender: 'Manager', loadStatus: 'success' })
    renderThinkingLog([step], 'done')
    expect(screen.getByText('Manager')).toBeInTheDocument()
  })

  it('shows sender badge for Researcher', () => {
    const step = makeTool({ sender: 'Researcher', loadStatus: 'success' })
    renderThinkingLog([step], 'done')
    expect(screen.getByText('Researcher')).toBeInTheDocument()
  })

  it('shows unknown sender label for unrecognized senders', () => {
    const step = makeTool({ sender: 'CustomAgent', loadStatus: 'success' })
    renderThinkingLog([step], 'done')
    expect(screen.getByText('CustomAgent')).toBeInTheDocument()
  })
})

// ── WebSearchResults ──────────────────────────────────────────────────────────

describe('ThinkingLog – WebSearchResults', () => {
  it('renders a Source card for each web_search result', () => {
    const step = makeTool({
      tool: 'web_search',
      loadStatus: 'success',
      summary: 'Found 2 results',
      data: {
        results: [
          { title: 'Wikipedia – Aspirin', url: 'https://en.wikipedia.org/wiki/Aspirin', snippet: 'Aspirin is a drug.' },
          { title: 'PubChem – Aspirin',   url: 'https://pubchem.ncbi.nlm.nih.gov/compound/Aspirin', snippet: '...' },
        ],
      },
    })
    renderThinkingLog([step], 'done')
    // Two Source cards should be rendered (one per result)
    expect(screen.getAllByTestId('source')).toHaveLength(2)
    // Title text appears in SourceTrigger label prop
    const sourceContent = screen.getAllByTestId('source').map((n) => n.textContent).join(' ')
    expect(sourceContent).toContain('Wikipedia – Aspirin')
    expect(sourceContent).toContain('PubChem – Aspirin')
  })

  it('renders nothing for web_search with no results', () => {
    const step = makeTool({ tool: 'web_search', loadStatus: 'success', summary: 'Found 0 results', data: { results: [] } })
    renderThinkingLog([step], 'done')
    expect(screen.queryByTestId('source')).not.toBeInTheDocument()
  })
})

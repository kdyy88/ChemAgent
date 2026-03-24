import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { TeamSettingsPopover } from '../TeamSettingsPopover'
import type { AgentModelConfig } from '@/lib/types'

// ── Hook mock ─────────────────────────────────────────────────────────────────

const mockSetAgentModels = vi.fn()
const mockClearTurns = vi.fn()
let mockTurns: unknown[] = []
let mockAgentModels: AgentModelConfig = {}

vi.mock('@/hooks/useChemAgent', () => ({
  useChemAgent: () => ({
    turns: mockTurns,
    agentModels: mockAgentModels,
    setAgentModels: mockSetAgentModels,
    clearTurns: mockClearTurns,
  }),
}))

// ── UI primitive mocks ────────────────────────────────────────────────────────

// Popover – always shows content (no floating overlay needed for tests)
vi.mock('@/components/ui/popover', () => ({
  Popover: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PopoverTrigger: ({ asChild, children }: { asChild?: boolean; children: React.ReactNode }) => (
    <>{children}</>
  ),
  PopoverContent: ({ children }: { children: React.ReactNode; align?: string }) => (
    <div data-testid="popover-content">{children}</div>
  ),
}))

// Select – renders a native <select> for easy interaction
vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    value,
    onValueChange,
  }: {
    children: React.ReactNode
    value?: string
    onValueChange?: (v: string) => void
  }) => (
    <select
      data-testid="select"
      value={value}
      onChange={(e) => onValueChange?.(e.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <option value={value}>{children}</option>
  ),
}))

// Dialog – shows content only when open=true
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    children,
    open,
    onOpenChange,
  }: {
    children: React.ReactNode
    open?: boolean
    onOpenChange?: (open: boolean) => void
  }) =>
    open ? (
      <div role="dialog" data-testid="confirm-dialog">
        {children}
      </div>
    ) : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
}))

vi.mock('@/components/ui/separator', () => ({
  Separator: () => <hr />,
}))

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockSetAgentModels.mockClear()
  mockClearTurns.mockClear()
  mockTurns = []
  mockAgentModels = {}
})

// ── Helpers ───────────────────────────────────────────────────────────────────

function getSelects() {
  return screen.getAllByTestId('select')
}

// Agent order: Manager[0], Visualizer[1], Researcher[2]
function changeManagerModel(value: string) {
  fireEvent.change(getSelects()[0], { target: { value } })
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('TeamSettingsPopover – rendering', () => {
  it('renders the settings trigger button', () => {
    render(<TeamSettingsPopover />)
    expect(screen.getByRole('button', { name: /settings/i })).toBeInTheDocument()
  })

  it('renders the popover content with Team Settings heading', () => {
    render(<TeamSettingsPopover />)
    // The text "Team Settings" appears twice: once in the trigger button label
    // (hidden span) and once in the popover heading (p.text-sm.font-semibold).
    const matches = screen.getAllByText('Team Settings')
    expect(matches.length).toBeGreaterThanOrEqual(1)
    // At least one is inside the popover content
    expect(screen.getByTestId('popover-content')).toHaveTextContent('Team Settings')
  })

  it('renders a select for each of the 3 agents', () => {
    render(<TeamSettingsPopover />)
    expect(getSelects()).toHaveLength(3)
  })

  it('shows model options in each select', () => {
    render(<TeamSettingsPopover />)
    const options = screen.getAllByRole('option', { name: /GPT/i })
    // 5 model options × 3 agents = 15 options total
    expect(options.length).toBe(15)
  })

  it('shows the "unlocked" footer hint when no turns', () => {
    render(<TeamSettingsPopover />)
    expect(screen.getByText(/settings are applied when the session starts/i)).toBeInTheDocument()
  })

  it('shows the "locked" footer hint when turns exist', () => {
    mockTurns = [{ id: 't1' }]
    render(<TeamSettingsPopover />)
    expect(screen.getByText(/switching models mid-conversation/i)).toBeInTheDocument()
  })
})

describe('TeamSettingsPopover – unlocked model change (no turns)', () => {
  it('calls setAgentModels immediately when model changed with no turns', () => {
    render(<TeamSettingsPopover />)
    changeManagerModel('gpt-4o')
    expect(mockSetAgentModels).toHaveBeenCalledTimes(1)
    expect(mockSetAgentModels).toHaveBeenCalledWith(
      expect.objectContaining({ manager: 'gpt-4o' })
    )
  })

  it('does NOT open the confirmation dialog when unlocked', () => {
    render(<TeamSettingsPopover />)
    changeManagerModel('gpt-4o')
    expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument()
  })

  it('does NOT call clearTurns when unlocked', () => {
    render(<TeamSettingsPopover />)
    changeManagerModel('gpt-4o')
    expect(mockClearTurns).not.toHaveBeenCalled()
  })

  it('is a no-op when selecting the same model that is already set', () => {
    mockAgentModels = { manager: 'gpt-4o-mini' }
    render(<TeamSettingsPopover />)
    // Selecting the same value — should return early
    changeManagerModel('gpt-4o-mini')
    expect(mockSetAgentModels).not.toHaveBeenCalled()
  })

  it('uses DEFAULT_MODEL (gpt-4o-mini) when key not present in agentModels', () => {
    mockAgentModels = {} // manager is undefined → defaults to gpt-4o-mini
    render(<TeamSettingsPopover />)
    const selects = getSelects()
    expect(selects[0]).toHaveValue('gpt-4o-mini')
  })
})

describe('TeamSettingsPopover – locked model change (with turns)', () => {
  beforeEach(() => {
    mockTurns = [{ id: 'existing-turn' }]
  })

  it('opens the confirmation dialog when a model is changed mid-conversation', () => {
    render(<TeamSettingsPopover />)
    changeManagerModel('gpt-4o')
    expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /切换模型/i })).toBeInTheDocument()
  })

  it('does NOT call setAgentModels immediately when locked', () => {
    render(<TeamSettingsPopover />)
    changeManagerModel('gpt-4o')
    expect(mockSetAgentModels).not.toHaveBeenCalled()
  })

  it('calls setAgentModels + clearTurns when user confirms', () => {
    render(<TeamSettingsPopover />)
    changeManagerModel('gpt-4o')

    fireEvent.click(screen.getByRole('button', { name: /确认并开启新对话/i }))

    expect(mockSetAgentModels).toHaveBeenCalledTimes(1)
    expect(mockSetAgentModels).toHaveBeenCalledWith(
      expect.objectContaining({ manager: 'gpt-4o' })
    )
    expect(mockClearTurns).toHaveBeenCalledTimes(1)
  })

  it('dismisses the dialog after confirming', () => {
    render(<TeamSettingsPopover />)
    changeManagerModel('gpt-4o')
    expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /确认并开启新对话/i }))
    expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument()
  })

  it('closes the dialog without applying changes when user cancels', () => {
    render(<TeamSettingsPopover />)
    changeManagerModel('gpt-4o')
    expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /取消/i }))

    expect(mockSetAgentModels).not.toHaveBeenCalled()
    expect(mockClearTurns).not.toHaveBeenCalled()
    expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument()
  })
})

describe('TeamSettingsPopover – agent label display', () => {
  it('shows the Manager agent row', () => {
    render(<TeamSettingsPopover />)
    expect(screen.getByText('Manager')).toBeInTheDocument()
  })

  it('shows the Visualizer agent row', () => {
    render(<TeamSettingsPopover />)
    expect(screen.getByText('Visualizer')).toBeInTheDocument()
  })

  it('shows the Researcher agent row', () => {
    render(<TeamSettingsPopover />)
    expect(screen.getByText('Researcher')).toBeInTheDocument()
  })
})

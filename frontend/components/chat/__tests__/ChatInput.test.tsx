import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ChatInput } from '../ChatInput'

// ── Hook mocks ─────────────────────────────────────────────────────────────────

const mockSendMessage = vi.fn()
let mockIsStreaming = false
let mockCurrentSmiles = ''
let mockActiveFunctionId: string | null = null

vi.mock('@/hooks/useChemAgent', () => ({
  useChemAgent: () => ({
    isStreaming: mockIsStreaming,
    sendMessage: mockSendMessage,
  }),
}))

vi.mock('@/store/workspaceStore', () => ({
  useWorkspaceStore: () => ({
    currentSmiles: mockCurrentSmiles,
    activeFunctionId: mockActiveFunctionId,
  }),
}))

// ── ui/prompt-input mock ──────────────────────────────────────────────────────
// Provide a lightweight textarea so tests can type into it.
// PromptInput wraps children and also renders a textarea that drives onValueChange.

vi.mock('@/components/ui/prompt-input', () => ({
  PromptInput: ({
    children,
    onValueChange,
    isLoading,
    disabled,
  }: {
    children: React.ReactNode
    onValueChange?: (v: string) => void
    isLoading?: boolean
    disabled?: boolean
    onSubmit?: () => void
    value?: string
    className?: string
  }) => (
    <div data-testid="prompt-input" data-loading={isLoading} data-disabled={disabled}>
      <textarea
        data-testid="prompt-textarea"
        onChange={(e) => onValueChange?.(e.target.value)}
      />
      {children}
    </div>
  ),
  PromptInputTextarea: () => null,
  PromptInputActions: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PromptInputAction: ({
    children,
  }: {
    children: React.ReactNode
    tooltip?: string
  }) => <>{children}</>,
}))

vi.mock('@/components/ui/loader', () => ({
  Loader: ({ variant, size, className }: { variant?: string; size?: string; className?: string }) => (
    <span data-testid="loader" data-variant={variant} data-size={size} className={className} />
  ),
}))

// ── Setup / helpers ───────────────────────────────────────────────────────────

beforeEach(() => {
  mockSendMessage.mockClear()
  mockIsStreaming = false
  mockCurrentSmiles = ''
  mockActiveFunctionId = null
})

function type(text: string) {
  fireEvent.change(screen.getByTestId('prompt-textarea'), { target: { value: text } })
}

function clickSend() {
  fireEvent.click(screen.getByRole('button', { name: /send/i }))
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('ChatInput – idle state', () => {
  it('renders the prompt input container', () => {
    render(<ChatInput />)
    expect(screen.getByTestId('prompt-input')).toBeInTheDocument()
  })

  it('shows the Send button (not streaming)', () => {
    render(<ChatInput />)
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument()
  })

  it('Send button is disabled when input is empty', () => {
    render(<ChatInput />)
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
  })

  it('Send button is enabled after typing a non-empty message', () => {
    render(<ChatInput />)
    type('Hello')
    expect(screen.getByRole('button', { name: /send/i })).not.toBeDisabled()
  })

  it('Send button stays disabled for whitespace-only input', () => {
    render(<ChatInput />)
    type('   ')
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
  })
})

describe('ChatInput – streaming state', () => {
  it('shows Loader + "Analyzing…" instead of Send button when streaming', () => {
    mockIsStreaming = true
    render(<ChatInput />)
    expect(screen.getByTestId('loader')).toBeInTheDocument()
    expect(screen.getByText('Analyzing…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /send/i })).not.toBeInTheDocument()
  })

  it('prompt-input receives isLoading=true when streaming', () => {
    mockIsStreaming = true
    render(<ChatInput />)
    expect(screen.getByTestId('prompt-input')).toHaveAttribute('data-loading', 'true')
  })
})

describe('ChatInput – sendMessage', () => {
  it('calls sendMessage with the typed text when Send is clicked', () => {
    render(<ChatInput />)
    type('What is aspirin?')
    clickSend()
    expect(mockSendMessage).toHaveBeenCalledTimes(1)
    expect(mockSendMessage).toHaveBeenCalledWith('What is aspirin?')
  })

  it('clears the input after sending', () => {
    render(<ChatInput />)
    type('Test message')
    clickSend()
    // After clear, button should be disabled again
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
  })

  it('does NOT call sendMessage when input is empty', () => {
    render(<ChatInput />)
    // Send is disabled so clicking it shouldn't trigger handleSubmit,
    // but test the guard explicitly by checking the mock isn't called
    fireEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(mockSendMessage).not.toHaveBeenCalled()
  })

  it('trims leading/trailing whitespace before sending', () => {
    render(<ChatInput />)
    type('  aspirin  ')
    clickSend()
    // sendMessage should be called with the trimmed value (no trailing context)
    expect(mockSendMessage).toHaveBeenCalledWith(expect.stringContaining('aspirin'))
    const called = mockSendMessage.mock.calls[0][0] as string
    // Leading/trailing whitespace stripped from user portion
    expect(called.startsWith('aspirin')).toBe(true)
  })
})

describe('ChatInput – SMILES context injection', () => {
  it('appends SMILES context when currentSmiles is set', () => {
    mockCurrentSmiles = 'CC(=O)OC1=CC=CC=C1C(=O)O'
    mockActiveFunctionId = 'descriptors'
    render(<ChatInput />)
    type('Describe this molecule')
    clickSend()

    const payload = mockSendMessage.mock.calls[0][0] as string
    expect(payload).toContain('Describe this molecule')
    expect(payload).toContain('[系统附加信息')
    expect(payload).toContain('CC(=O)OC1=CC=CC=C1C(=O)O')
    expect(payload).toContain('descriptors')
  })

  it('does NOT append context when currentSmiles is empty', () => {
    mockCurrentSmiles = ''
    render(<ChatInput />)
    type('Show me something')
    clickSend()

    const payload = mockSendMessage.mock.calls[0][0] as string
    expect(payload).not.toContain('[系统附加信息')
    expect(payload).toBe('Show me something')
  })
})

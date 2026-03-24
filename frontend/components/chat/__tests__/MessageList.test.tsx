import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageList } from '../MessageList'
import type { Turn } from '@/lib/types'

// ── Stubs ─────────────────────────────────────────────────────────────────────

const mockTurns: Turn[] = []

vi.mock('@/hooks/useChemAgent', () => ({
  useChemAgent: () => ({ turns: mockTurns }),
}))

vi.mock('../MessageBubble', () => ({
  MessageBubble: ({ turn }: { turn: Turn }) => (
    <div data-testid="message-bubble" data-turn-id={turn.id} />
  ),
}))

// ChatContainer primitives — simple pass-throughs
vi.mock('@/components/ui/chat-container', () => ({
  ChatContainerRoot: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div data-testid="chat-root" className={className}>{children}</div>
  ),
  ChatContainerContent: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div data-testid="chat-content" className={className}>{children}</div>
  ),
  ChatContainerScrollAnchor: () => <div data-testid="scroll-anchor" />,
}))

vi.mock('@/components/ui/scroll-button', () => ({
  ScrollButton: () => <button data-testid="scroll-button" />,
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeTurn(id: string, msg = 'Hello'): Turn {
  return {
    id,
    userMessage: msg,
    steps: [],
    artifacts: [],
    status: 'done',
    startedAt: Date.now(),
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('MessageList – empty state', () => {
  beforeEach(() => {
    mockTurns.length = 0
  })

  it('shows the "Ask me about any chemical compound" heading', () => {
    render(<MessageList />)
    expect(screen.getByText('Ask me about any chemical compound')).toBeInTheDocument()
  })

  it('shows the example hint text', () => {
    render(<MessageList />)
    expect(screen.getByText(/Aspirin/)).toBeInTheDocument()
  })

  it('does NOT render any MessageBubble', () => {
    render(<MessageList />)
    expect(screen.queryByTestId('message-bubble')).not.toBeInTheDocument()
  })

  it('renders the scroll button', () => {
    render(<MessageList />)
    expect(screen.getByTestId('scroll-button')).toBeInTheDocument()
  })
})

describe('MessageList – with turns', () => {
  it('renders one MessageBubble per turn', () => {
    mockTurns.length = 0
    mockTurns.push(makeTurn('t1', 'First'), makeTurn('t2', 'Second'))
    render(<MessageList />)

    const bubbles = screen.getAllByTestId('message-bubble')
    expect(bubbles).toHaveLength(2)
  })

  it('passes the correct turn id to each MessageBubble', () => {
    mockTurns.length = 0
    mockTurns.push(makeTurn('turn-abc'), makeTurn('turn-xyz'))
    render(<MessageList />)

    const bubbles = screen.getAllByTestId('message-bubble')
    expect(bubbles[0]).toHaveAttribute('data-turn-id', 'turn-abc')
    expect(bubbles[1]).toHaveAttribute('data-turn-id', 'turn-xyz')
  })

  it('does NOT show the empty-state text when turns exist', () => {
    mockTurns.length = 0
    mockTurns.push(makeTurn('t1'))
    render(<MessageList />)
    expect(screen.queryByText('Ask me about any chemical compound')).not.toBeInTheDocument()
  })

  it('renders the chat container root', () => {
    mockTurns.length = 0
    mockTurns.push(makeTurn('t1'))
    render(<MessageList />)
    expect(screen.getByTestId('chat-root')).toBeInTheDocument()
  })

  it('renders the scroll anchor', () => {
    mockTurns.length = 0
    mockTurns.push(makeTurn('t1'))
    render(<MessageList />)
    expect(screen.getByTestId('scroll-anchor')).toBeInTheDocument()
  })
})

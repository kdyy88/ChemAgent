import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageBubble } from '../MessageBubble'
import type { Turn } from '@/lib/types'

// ── Sub-component stubs ───────────────────────────────────────────────────────

vi.mock('../ThinkingLog', () => ({
  ThinkingLog: ({ steps, status }: { steps: unknown[]; status: string }) => (
    <div data-testid="thinking-log" data-steps={steps.length} data-status={status} />
  ),
}))

vi.mock('../ArtifactGallery', () => ({
  ArtifactGallery: ({ artifacts }: { artifacts: unknown[] }) => (
    <div data-testid="artifact-gallery" data-count={artifacts.length} />
  ),
}))

// ui/message – simple wrappers that render children
vi.mock('@/components/ui/message', () => ({
  Message: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div data-testid="message" className={className}>{children}</div>
  ),
  MessageContent: ({
    children,
    markdown,
    className,
  }: {
    children: React.ReactNode
    markdown?: boolean
    className?: string
  }) => (
    <div
      data-testid="message-content"
      data-markdown={markdown}
      className={className}
    >
      {children}
    </div>
  ),
}))

vi.mock('@/components/ui/loader', () => ({
  Loader: ({ variant, size }: { variant?: string; size?: string }) => (
    <span data-testid="loader" data-variant={variant} data-size={size} />
  ),
}))

vi.mock('@/components/ui/skeleton', () => ({
  Skeleton: ({ className }: { className?: string }) => (
    <div data-testid="skeleton" className={className} />
  ),
}))

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeTurn(overrides: Partial<Turn> = {}): Turn {
  return {
    id: 'turn-1',
    userMessage: 'What is aspirin?',
    steps: [],
    artifacts: [],
    status: 'done',
    startedAt: Date.now(),
    ...overrides,
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('MessageBubble – user bubble', () => {
  it('renders the user message text', () => {
    render(<MessageBubble turn={makeTurn({ userMessage: 'Tell me about caffeine' })} />)
    expect(screen.getByText('Tell me about caffeine')).toBeInTheDocument()
  })

  it('hides the user bubble for greeting turns', () => {
    render(<MessageBubble turn={makeTurn({ isGreeting: true, userMessage: 'Hello!' })} />)
    // Greeting turns should not show the user message in a right-aligned bubble
    expect(screen.queryByText('Hello!')).not.toBeInTheDocument()
  })

  it('shows the user bubble for non-greeting turns', () => {
    render(<MessageBubble turn={makeTurn({ isGreeting: false, userMessage: 'Hello!' })} />)
    expect(screen.getByText('Hello!')).toBeInTheDocument()
  })
})

describe('MessageBubble – thinking state (no content)', () => {
  it('shows skeleton placeholders when thinking and no final answer', () => {
    render(<MessageBubble turn={makeTurn({ status: 'thinking', finalAnswer: undefined })} />)
    const skeletons = screen.getAllByTestId('skeleton')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('does NOT render ArtifactGallery while thinking', () => {
    render(<MessageBubble turn={makeTurn({ status: 'thinking' })} />)
    expect(screen.queryByTestId('artifact-gallery')).not.toBeInTheDocument()
  })

  it('renders ThinkingLog while thinking', () => {
    render(<MessageBubble turn={makeTurn({ status: 'thinking' })} />)
    expect(screen.getByTestId('thinking-log')).toBeInTheDocument()
    expect(screen.getByTestId('thinking-log')).toHaveAttribute('data-status', 'thinking')
  })
})

describe('MessageBubble – streaming state (thinking + content)', () => {
  it('shows the streaming text content as plain text', () => {
    render(
      <MessageBubble
        turn={makeTurn({ status: 'thinking', finalAnswer: 'Aspirin is a pain reliever' })}
      />
    )
    expect(screen.getByText('Aspirin is a pain reliever')).toBeInTheDocument()
  })

  it('shows the Loader during streaming', () => {
    render(
      <MessageBubble
        turn={makeTurn({ status: 'thinking', finalAnswer: 'Streaming text...' })}
      />
    )
    expect(screen.getByTestId('loader')).toBeInTheDocument()
  })

  it('does NOT use Markdown during streaming (for performance)', () => {
    render(
      <MessageBubble
        turn={makeTurn({ status: 'thinking', finalAnswer: '**bold text**' })}
      />
    )
    // During streaming the raw text is rendered as plain whitespace-pre-wrap
    // The Markdown-enabled MessageContent should NOT be used
    const markdownContent = screen.queryByTestId('message-content')
    if (markdownContent) {
      expect(markdownContent).not.toHaveAttribute('data-markdown', 'true')
    }
    // Raw asterisks should appear in DOM, not rendered as <strong>
    expect(screen.getByText('**bold text**')).toBeInTheDocument()
  })
})

describe('MessageBubble – done state', () => {
  it('renders final answer in Markdown MessageContent', () => {
    render(
      <MessageBubble
        turn={makeTurn({ status: 'done', finalAnswer: 'Aspirin **relieves** pain.' })}
      />
    )
    // There are two message-content elements: one for the user bubble and one
    // for the agent response. Find the agent one (data-markdown=true).
    const allContent = screen.getAllByTestId('message-content')
    const markdownContent = allContent.find(
      (el) => el.getAttribute('data-markdown') === 'true',
    )
    expect(markdownContent).toBeInTheDocument()
    expect(markdownContent?.textContent).toContain('Aspirin **relieves** pain.')
  })

  it('renders ArtifactGallery when done', () => {
    render(
      <MessageBubble
        turn={makeTurn({
          status: 'done',
          artifacts: [{ artifactId: 'a1', kind: 'image', mimeType: 'image/png', data: 'aaa', encoding: 'base64' }],
        })}
      />
    )
    expect(screen.getByTestId('artifact-gallery')).toBeInTheDocument()
    expect(screen.getByTestId('artifact-gallery')).toHaveAttribute('data-count', '1')
  })

  it('renders ThinkingLog in done state too', () => {
    render(<MessageBubble turn={makeTurn({ status: 'done' })} />)
    expect(screen.getByTestId('thinking-log')).toHaveAttribute('data-status', 'done')
  })

  it('renders nothing for content area when done with no finalAnswer', () => {
    render(<MessageBubble turn={makeTurn({ status: 'done', finalAnswer: undefined })} />)
    // No Markdown content panel, no skeleton, no streaming loader
    const allContent = screen.getAllByTestId('message-content')
    // Only the user-bubble MessageContent should exist (not data-markdown)
    expect(allContent.every((el) => el.getAttribute('data-markdown') !== 'true')).toBe(true)
    expect(screen.queryByTestId('skeleton')).not.toBeInTheDocument()
    expect(screen.queryByTestId('loader')).not.toBeInTheDocument()
  })
})

describe('MessageBubble – ChemAgent attribution', () => {
  it('shows "ChemAgent" label', () => {
    render(<MessageBubble turn={makeTurn()} />)
    expect(screen.getByText('ChemAgent')).toBeInTheDocument()
  })
})

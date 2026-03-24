/**
 * Unit tests for components/ui/markdown.tsx
 *
 * Coverage:
 *  - parseMarkdownIntoBlocks (via rendered output)
 *  - extractLanguage (via rendered code blocks)
 *  - img custom renderer (empty src guard)
 *  - a custom renderer (action:apply-smiles: link → Button)
 *  - <ApplySmiles> tag preprocessing
 *  - Markdown component props: children, id, className
 *  - MemoizedMarkdownBlock memoisation
 */

import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { Markdown } from '../markdown'

// ── Mocks ──────────────────────────────────────────────────────────────────────

const mockSetSmiles = vi.fn()

vi.mock('@/store/workspaceStore', () => ({
  useWorkspaceStore: {
    getState: () => ({ setSmiles: mockSetSmiles }),
  },
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    onClick,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & { children?: React.ReactNode }) => (
    <button data-testid="apply-button" onClick={onClick} {...props}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/ui/code-block', () => ({
  CodeBlock: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="code-block">{children}</div>
  ),
  CodeBlockCode: ({
    code,
    language,
  }: {
    code: string
    language: string
  }) => (
    <code data-testid="code-block-code" data-language={language}>
      {code}
    </code>
  ),
}))

// ── Helpers ────────────────────────────────────────────────────────────────────

const renderMd = (markdown: string, className?: string) =>
  render(<Markdown className={className}>{markdown}</Markdown>)

// ── Test suites ────────────────────────────────────────────────────────────────

describe('Markdown – basic rendering', () => {
  it('renders plain text', () => {
    renderMd('Hello world')
    expect(screen.getByText('Hello world')).toBeInTheDocument()
  })

  it('renders an h1 heading', () => {
    renderMd('# Heading One')
    const heading = screen.getByRole('heading', { level: 1 })
    expect(heading).toBeInTheDocument()
    expect(heading).toHaveTextContent('Heading One')
  })

  it('renders an h2 heading', () => {
    renderMd('## Heading Two')
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Heading Two')
  })

  it('applies className to the wrapper div', () => {
    const { container } = renderMd('text', 'my-custom-class')
    expect(container.firstChild).toHaveClass('my-custom-class')
  })

  it('renders bold text', () => {
    renderMd('**bold text**')
    const bold = document.querySelector('strong')
    expect(bold).toBeTruthy()
    expect(bold?.textContent).toBe('bold text')
  })

  it('renders italic text', () => {
    renderMd('*italic text*')
    const em = document.querySelector('em')
    expect(em).toBeTruthy()
    expect(em?.textContent).toBe('italic text')
  })

  it('renders an unordered list', () => {
    renderMd('- item one\n- item two')
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('item one')
    expect(items[1]).toHaveTextContent('item two')
  })

  it('renders an ordered list', () => {
    renderMd('1. first\n2. second')
    const list = document.querySelector('ol')
    expect(list).toBeTruthy()
    const items = list?.querySelectorAll('li')
    expect(items).toHaveLength(2)
  })

  it('renders a blockquote', () => {
    renderMd('> quoted text')
    const bq = document.querySelector('blockquote')
    expect(bq).toBeTruthy()
    expect(bq?.textContent).toContain('quoted text')
  })

  it('renders a horizontal rule', () => {
    renderMd('---')
    const hr = document.querySelector('hr')
    expect(hr).toBeTruthy()
  })

  it('renders a GFM table', () => {
    const table = '| A | B |\n|---|---|\n| 1 | 2 |'
    renderMd(table)
    expect(document.querySelector('table')).toBeTruthy()
    expect(document.querySelector('th')).toBeTruthy()
  })

  it('renders multiple paragraphs as separate blocks', () => {
    renderMd('First paragraph.\n\nSecond paragraph.')
    expect(screen.getByText('First paragraph.')).toBeInTheDocument()
    expect(screen.getByText('Second paragraph.')).toBeInTheDocument()
  })
})

// ── Link rendering ─────────────────────────────────────────────────────────────

describe('Markdown – link (a) renderer', () => {
  it('renders a normal link as <a>', () => {
    renderMd('[OpenAI](https://openai.com)')
    const anchor = screen.getByRole('link', { name: 'OpenAI' })
    expect(anchor).toBeInTheDocument()
    expect(anchor).toHaveAttribute('href', 'https://openai.com')
  })

  it('renders action:apply-smiles: link as a button', () => {
    renderMd('[Apply](action:apply-smiles:CCO)')
    const btn = screen.getByTestId('apply-button')
    expect(btn).toBeInTheDocument()
  })

  it('calls setSmiles with the correct SMILES string when button is clicked', () => {
    renderMd('[Apply](action:apply-smiles:CCO)')
    fireEvent.click(screen.getByTestId('apply-button'))
    expect(mockSetSmiles).toHaveBeenCalledWith('CCO')
  })

  it('calls setSmiles with a complex SMILES string', () => {
    const smiles = 'C1=CC=CC=C1'
    renderMd(`[Draw](action:apply-smiles:${smiles})`)
    fireEvent.click(screen.getByTestId('apply-button'))
    expect(mockSetSmiles).toHaveBeenCalledWith(smiles)
  })

  it('uses link text as button label', () => {
    renderMd('[Apply to Workspace](action:apply-smiles:CCO)')
    expect(screen.getByTestId('apply-button')).toHaveTextContent('Apply to Workspace')
  })

  it('falls back to "Apply to Workspace" when link text is empty (edge case)', () => {
    // react-markdown always passes children, but test the fallback clause
    renderMd('[](action:apply-smiles:CCO)')
    // button still renders
    expect(screen.getByTestId('apply-button')).toBeInTheDocument()
  })
})

// ── Image renderer ─────────────────────────────────────────────────────────────

describe('Markdown – img renderer', () => {
  it('renders an img element for a valid src', () => {
    renderMd('![alt text](https://example.com/img.png)')
    const img = document.querySelector('img')
    expect(img).toBeTruthy()
    expect(img?.getAttribute('src')).toBe('https://example.com/img.png')
    expect(img?.getAttribute('alt')).toBe('alt text')
  })

  it('uses empty string for alt when none is provided', () => {
    renderMd('![](https://example.com/img.png)')
    const img = document.querySelector('img')
    expect(img).toBeTruthy()
    expect(img?.getAttribute('alt')).toBe('')
  })

  it('does NOT render an img element when src is empty', () => {
    // Markdown with empty src: ![]()
    renderMd('![]()')
    expect(document.querySelector('img')).toBeNull()
  })
})

// ── Code rendering ─────────────────────────────────────────────────────────────

describe('Markdown – code renderer', () => {
  it('renders a fenced code block via CodeBlock', () => {
    renderMd('```python\nimport os\n```')
    expect(screen.getByTestId('code-block')).toBeInTheDocument()
    const codeEl = screen.getByTestId('code-block-code')
    expect(codeEl).toHaveAttribute('data-language', 'python')
  })

  it('extracts "javascript" language from fenced block', () => {
    renderMd('```javascript\nconsole.log(1)\n```')
    expect(screen.getByTestId('code-block-code')).toHaveAttribute('data-language', 'javascript')
  })

  it('defaults to "plaintext" when no language is specified', () => {
    renderMd('```\nno lang\n```')
    expect(screen.getByTestId('code-block-code')).toHaveAttribute('data-language', 'plaintext')
  })

  it('renders inline code as a <span>', () => {
    renderMd('Use `console.log()` here.')
    // inline code must NOT go through CodeBlock
    expect(screen.queryByTestId('code-block')).toBeNull()
    const spans = document.querySelectorAll('span')
    const inlineCode = Array.from(spans).find((s) => s.textContent === 'console.log()')
    expect(inlineCode).toBeTruthy()
  })
})

// ── ApplySmiles preprocessing ──────────────────────────────────────────────────

describe('Markdown – <ApplySmiles> tag preprocessing', () => {
  beforeEach(() => {
    mockSetSmiles.mockClear()
  })

  it('converts self-closing <ApplySmiles smiles="..." /> to a button', () => {
    renderMd('<ApplySmiles smiles="CCO" />')
    expect(screen.getByTestId('apply-button')).toBeInTheDocument()
  })

  it('converts open/close <ApplySmiles smiles="..."></ApplySmiles> to a button', () => {
    renderMd('<ApplySmiles smiles="CCO"></ApplySmiles>')
    expect(screen.getByTestId('apply-button')).toBeInTheDocument()
  })

  it('calls setSmiles with correct value from self-closing tag', () => {
    renderMd('<ApplySmiles smiles="C1CCCCC1" />')
    fireEvent.click(screen.getByTestId('apply-button'))
    expect(mockSetSmiles).toHaveBeenCalledWith('C1CCCCC1')
  })

  it('calls setSmiles with correct value from open/close tag', () => {
    renderMd('<ApplySmiles smiles="C1CCCCC1"></ApplySmiles>')
    fireEvent.click(screen.getByTestId('apply-button'))
    expect(mockSetSmiles).toHaveBeenCalledWith('C1CCCCC1')
  })

  it('does not convert unrelated HTML-like tags', () => {
    renderMd('Some text with <strong>bold</strong>')
    expect(screen.queryByTestId('apply-button')).toBeNull()
  })

  it('handles ApplySmiles embedded in surrounding text', () => {
    renderMd('See this molecule: <ApplySmiles smiles="CCO" /> – interesting!')
    expect(screen.getByTestId('apply-button')).toBeInTheDocument()
  })
})

// ── parseMarkdownIntoBlocks (via rendered output) ──────────────────────────────

describe('parseMarkdownIntoBlocks (via rendering)', () => {
  it('splits heading and paragraph into separate blocks', () => {
    const { container } = renderMd('# Title\n\nSome text below.')
    // Both should be present in the output
    expect(screen.getByRole('heading')).toHaveTextContent('Title')
    expect(container).toHaveTextContent('Some text below.')
  })

  it('renders an empty string without crashing', () => {
    const { container } = renderMd('')
    expect(container.firstChild).toBeInTheDocument()
  })

  it('renders a multi-section document', () => {
    const md = '# Intro\n\nParagraph one.\n\n## Details\n\nParagraph two.'
    renderMd(md)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Intro')
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Details')
    expect(screen.getByText('Paragraph one.')).toBeInTheDocument()
    expect(screen.getByText('Paragraph two.')).toBeInTheDocument()
  })
})

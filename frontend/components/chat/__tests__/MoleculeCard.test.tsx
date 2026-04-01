import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MoleculeCard } from '../MoleculeCard'

// ── Mock framer-motion ────────────────────────────────────────────────────────
// framer-motion uses ResizeObserver and complex animation APIs unavailable in
// jsdom. Replace motion.div with a plain forwardRef div so tests stay fast.

vi.mock('framer-motion', () => ({
  motion: {
    div: React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
      ({ children, ...props }, ref) => <div ref={ref} {...props}>{children}</div>
    ),
  },
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

const FAKE_B64 = 'iVBORw0KGgoAAAANSUhEUg=='
const DATA_URL = `data:image/png;base64,${FAKE_B64}`

function renderCard(image = FAKE_B64, title?: string | null) {
  return render(<MoleculeCard image={image} title={title} />)
}

// ── Thumbnail tests ───────────────────────────────────────────────────────────

describe('MoleculeCard – thumbnail', () => {
  it('renders a thumbnail img with correct data URL', () => {
    renderCard()
    const imgs = screen.getAllByRole('img')
    expect(imgs.some((img) => img.getAttribute('src') === DATA_URL)).toBe(true)
  })

  it('uses the title as alt text when provided', () => {
    renderCard(FAKE_B64, 'Aspirin')
    const thumbnailImg = screen.getAllByRole('img').find(
      (img) => img.getAttribute('alt') === 'Aspirin',
    )
    expect(thumbnailImg).toBeInTheDocument()
  })

  it('falls back to "Molecule structure" alt when title is absent', () => {
    renderCard()
    const thumbnailImg = screen.getAllByRole('img').find(
      (img) => img.getAttribute('alt') === 'Molecule structure',
    )
    expect(thumbnailImg).toBeInTheDocument()
  })

  it('shows title label below the thumbnail', () => {
    renderCard(FAKE_B64, 'Ibuprofen')
    expect(screen.getByText('Ibuprofen')).toBeInTheDocument()
  })

  it('does NOT show label element when title is absent', () => {
    const { container } = renderCard()
    const spans = container.querySelectorAll('span.text-muted-foreground')
    expect(spans).toHaveLength(0)
  })
})

// ── Dialog tests ──────────────────────────────────────────────────────────────

describe('MoleculeCard – dialog', () => {
  it('dialog is closed initially', () => {
    renderCard(FAKE_B64, 'Aspirin')
    // DialogTitle should not be visible yet
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('opens the full-size dialog when the thumbnail button is clicked', () => {
    renderCard(FAKE_B64, 'Aspirin')
    const button = screen.getByRole('button', { name: /view full size/i })
    fireEvent.click(button)
    // Dialog should now be in the DOM (Radix renders into document.body via portal)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // "Aspirin" appears in both thumbnail label and dialog title — that is fine
    expect(screen.getAllByText('Aspirin').length).toBeGreaterThanOrEqual(2)
  })

  it('shows "Molecule Structure" dialog title when no title given', () => {
    renderCard()
    const button = screen.getByRole('button', { name: /view full size: molecule/i })
    fireEvent.click(button)
    expect(screen.getByText('Molecule Structure')).toBeInTheDocument()
  })

  it('dialog contains a full-size img with the same data URL', () => {
    renderCard(FAKE_B64, 'Test')
    fireEvent.click(screen.getByRole('button', { name: /view full size/i }))

    const dialog = screen.getByRole('dialog')
    const dialogImg = dialog.querySelector('img')
    expect(dialogImg).not.toBeNull()
    expect(dialogImg!.getAttribute('src')).toBe(DATA_URL)
  })

  it('closes the dialog when a close control is activated', () => {
    renderCard(FAKE_B64, 'Aspirin')
    fireEvent.click(screen.getByRole('button', { name: /view full size/i }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    // Two close controls exist: Radix auto-close (top-right X) and the explicit
    // footer Close button. Clicking either should dismiss the dialog.
    const closeButtons = screen.getAllByRole('button', { name: /close/i })
    expect(closeButtons.length).toBeGreaterThanOrEqual(1)
    fireEvent.click(closeButtons[0])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

// ── Download link tests ───────────────────────────────────────────────────────

describe('MoleculeCard – download link', () => {
  it('download link has correct href (data URL)', () => {
    renderCard(FAKE_B64, 'Aspirin')
    fireEvent.click(screen.getByRole('button', { name: /view full size/i }))
    const link = screen.getByRole('link', { name: /download png/i })
    expect(link).toHaveAttribute('href', DATA_URL)
  })

  it('download filename uses the title', () => {
    renderCard(FAKE_B64, 'Aspirin')
    fireEvent.click(screen.getByRole('button', { name: /view full size/i }))
    const link = screen.getByRole('link', { name: /download png/i })
    expect(link).toHaveAttribute('download', 'Aspirin.png')
  })

  it('download filename falls back to "molecule.png" when title is absent', () => {
    renderCard()
    fireEvent.click(screen.getByRole('button', { name: /view full size: molecule/i }))
    const link = screen.getByRole('link', { name: /download png/i })
    expect(link).toHaveAttribute('download', 'molecule.png')
  })
})

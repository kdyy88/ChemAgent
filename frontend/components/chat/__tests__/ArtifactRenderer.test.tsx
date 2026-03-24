import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ArtifactRenderer } from '../ArtifactRenderer'
import type { Artifact } from '@/lib/types'

// ── Stubs ─────────────────────────────────────────────────────────────────────

vi.mock('../MoleculeCard', () => ({
  MoleculeCard: ({ image, title }: { image: string; title?: string | null }) => (
    <div data-testid="molecule-card" data-image={image} data-title={title ?? ''} />
  ),
}))

vi.mock('./LipinskiCard', () => ({
  LipinskiCard: ({ data }: { data: unknown }) => (
    <div data-testid="lipinski-card" data-type={(data as Record<string, unknown>)?.type as string} />
  ),
}))

// LipinskiCard is imported from the same directory, not via alias
vi.mock('../LipinskiCard', () => ({
  LipinskiCard: ({ data }: { data: unknown }) => (
    <div data-testid="lipinski-card" data-type={(data as Record<string, unknown>)?.type as string} />
  ),
}))

// ── URL API stubs ─────────────────────────────────────────────────────────────

const FAKE_URL = 'blob:http://localhost/fake-uuid'

beforeEach(() => {
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn().mockReturnValue(FAKE_URL),
    revokeObjectURL: vi.fn(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ── Fixtures ──────────────────────────────────────────────────────────────────

const imageArtifact: Artifact = {
  artifactId: 'art-img',
  kind: 'image',
  mimeType: 'image/png',
  data: 'base64abc',
  encoding: 'base64',
  title: 'Molecule',
}

const lipinskiArtifact: Artifact = {
  artifactId: 'art-lip',
  kind: 'json',
  mimeType: 'application/json',
  data: { type: 'lipinski', mw: 180, logp: 1.2, hbd: 1, hba: 4, tpsa: 63.6, lipinski_pass: true, is_valid: true },
  encoding: 'json',
  title: 'Lipinski',
}

const jsonArtifact: Artifact = {
  artifactId: 'art-json',
  kind: 'json',
  mimeType: 'application/json',
  data: { foo: 'bar', nested: { baz: 42 } },
  encoding: 'json',
  title: 'Metadata',
}

const textArtifact: Artifact = {
  artifactId: 'art-txt',
  kind: 'text',
  mimeType: 'text/plain',
  data: 'Hello world content',
  encoding: 'utf8',
  title: 'Notes',
}

// ── Routing tests ─────────────────────────────────────────────────────────────

describe('ArtifactRenderer – routing', () => {
  it('renders MoleculeCard for image/png artifact with string data', () => {
    render(<ArtifactRenderer artifact={imageArtifact} />)
    expect(screen.getByTestId('molecule-card')).toBeInTheDocument()
    expect(screen.getByTestId('molecule-card')).toHaveAttribute('data-image', 'base64abc')
    expect(screen.queryByTestId('lipinski-card')).not.toBeInTheDocument()
  })

  it('renders MoleculeCard for image/svg+xml artifact', () => {
    render(<ArtifactRenderer artifact={{ ...imageArtifact, mimeType: 'image/svg+xml' }} />)
    expect(screen.getByTestId('molecule-card')).toBeInTheDocument()
  })

  it('renders LipinskiCard for json artifact with type=lipinski', () => {
    render(<ArtifactRenderer artifact={lipinskiArtifact} />)
    expect(screen.getByTestId('lipinski-card')).toBeInTheDocument()
    expect(screen.getByTestId('lipinski-card')).toHaveAttribute('data-type', 'lipinski')
    expect(screen.queryByTestId('molecule-card')).not.toBeInTheDocument()
  })

  it('does NOT render LipinskiCard for json artifact without type tag', () => {
    render(<ArtifactRenderer artifact={jsonArtifact} />)
    expect(screen.queryByTestId('lipinski-card')).not.toBeInTheDocument()
  })

  it('renders JsonArtifactCard for application/json artifact', () => {
    render(<ArtifactRenderer artifact={jsonArtifact} />)
    expect(screen.queryByTestId('molecule-card')).not.toBeInTheDocument()
    expect(screen.queryByTestId('lipinski-card')).not.toBeInTheDocument()
    // JsonArtifactCard shows "Download JSON" button
    expect(screen.getByRole('link', { name: /download json/i })).toBeInTheDocument()
  })

  it('renders JsonArtifactCard for encoding=json artifact', () => {
    const encodingJson: Artifact = { ...textArtifact, encoding: 'json', mimeType: 'text/plain', data: { a: 1 } }
    render(<ArtifactRenderer artifact={encodingJson} />)
    expect(screen.getByRole('link', { name: /download json/i })).toBeInTheDocument()
  })

  it('renders TextArtifactCard for plain text artifact', () => {
    render(<ArtifactRenderer artifact={textArtifact} />)
    expect(screen.queryByTestId('molecule-card')).not.toBeInTheDocument()
    expect(screen.queryByTestId('lipinski-card')).not.toBeInTheDocument()
    // TextArtifactCard shows generic "Download" link
    expect(screen.getByRole('link', { name: /^download$/i })).toBeInTheDocument()
    expect(screen.getByText('Hello world content')).toBeInTheDocument()
  })
})

// ── JsonArtifactCard ──────────────────────────────────────────────────────────

describe('ArtifactRenderer – JsonArtifactCard', () => {
  it('shows pretty-printed JSON', () => {
    render(<ArtifactRenderer artifact={jsonArtifact} />)
    expect(screen.getByText(/"foo": "bar"/)).toBeInTheDocument()
  })

  it('shows the artifact title', () => {
    render(<ArtifactRenderer artifact={jsonArtifact} />)
    expect(screen.getByText('Metadata')).toBeInTheDocument()
  })

  it('falls back to "JSON Artifact" when title is absent', () => {
    render(<ArtifactRenderer artifact={{ ...jsonArtifact, title: null }} />)
    expect(screen.getByText('JSON Artifact')).toBeInTheDocument()
  })

  it('download link href is a blob URL', () => {
    render(<ArtifactRenderer artifact={jsonArtifact} />)
    const link = screen.getByRole('link', { name: /download json/i })
    expect(link).toHaveAttribute('href', FAKE_URL)
  })

  it('download filename uses artifactId', () => {
    render(<ArtifactRenderer artifact={jsonArtifact} />)
    const link = screen.getByRole('link', { name: /download json/i })
    expect(link).toHaveAttribute('download', 'art-json.json')
  })
})

// ── TextArtifactCard ──────────────────────────────────────────────────────────

describe('ArtifactRenderer – TextArtifactCard', () => {
  it('shows the artifact title', () => {
    render(<ArtifactRenderer artifact={textArtifact} />)
    expect(screen.getByText('Notes')).toBeInTheDocument()
  })

  it('shows text content', () => {
    render(<ArtifactRenderer artifact={textArtifact} />)
    expect(screen.getByText('Hello world content')).toBeInTheDocument()
  })

  it('falls back to "Artifact" title when absent', () => {
    render(<ArtifactRenderer artifact={{ ...textArtifact, title: null }} />)
    expect(screen.getByText('Artifact')).toBeInTheDocument()
  })

  it('download link uses blob URL', () => {
    render(<ArtifactRenderer artifact={textArtifact} />)
    const link = screen.getByRole('link', { name: /^download$/i })
    expect(link).toHaveAttribute('href', FAKE_URL)
  })

  it('download filename uses artifactId with .txt extension', () => {
    render(<ArtifactRenderer artifact={textArtifact} />)
    const link = screen.getByRole('link', { name: /^download$/i })
    expect(link).toHaveAttribute('download', 'art-txt.txt')
  })

  it('serializes object data as JSON string for display', () => {
    const objData: Artifact = { ...textArtifact, data: { key: 'value' }, encoding: 'utf8', mimeType: 'text/plain' }
    render(<ArtifactRenderer artifact={objData} />)
    expect(screen.getByText(/"key": "value"/)).toBeInTheDocument()
  })
})

// ── URL.createObjectURL / revokeObjectURL ─────────────────────────────────────

describe('ArtifactRenderer – object URL lifecycle', () => {
  it('calls URL.createObjectURL when rendering a text card', () => {
    render(<ArtifactRenderer artifact={textArtifact} />)
    expect(URL.createObjectURL).toHaveBeenCalled()
  })

  it('calls URL.createObjectURL for JSON card', () => {
    render(<ArtifactRenderer artifact={jsonArtifact} />)
    expect(URL.createObjectURL).toHaveBeenCalled()
  })
})

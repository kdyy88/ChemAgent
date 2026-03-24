import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ArtifactGallery } from '../ArtifactGallery'
import type { Artifact } from '@/lib/types'

// ── Stubs for heavyweight sub-components ────────────────────────────────────

vi.mock('../MoleculeCard', () => ({
  MoleculeCard: ({ image, title }: { image: string; title?: string | null }) => (
    <div data-testid="molecule-card" data-image={image} data-title={title ?? ''} />
  ),
}))

vi.mock('../ArtifactRenderer', () => ({
  ArtifactRenderer: ({ artifact }: { artifact: Artifact }) => (
    <div data-testid="artifact-renderer" data-artifact-id={artifact.artifactId} />
  ),
}))

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeImageArtifact(overrides?: Partial<Artifact>): Artifact {
  return {
    artifactId: 'art-img-1',
    kind: 'image',
    mimeType: 'image/png',
    data: 'base64encodeddata',
    encoding: 'base64',
    title: 'Aspirin',
    ...overrides,
  }
}

function makeJsonArtifact(overrides?: Partial<Artifact>): Artifact {
  return {
    artifactId: 'art-json-1',
    kind: 'json',
    mimeType: 'application/json',
    data: { type: 'lipinski', mw: 180 },
    encoding: 'json',
    title: 'Properties',
    ...overrides,
  }
}

function makeTextArtifact(overrides?: Partial<Artifact>): Artifact {
  return {
    artifactId: 'art-txt-1',
    kind: 'text',
    mimeType: 'text/plain',
    data: 'Hello world',
    encoding: 'utf8',
    title: 'Note',
    ...overrides,
  }
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('ArtifactGallery', () => {
  it('renders nothing when artifacts array is empty', () => {
    const { container } = render(<ArtifactGallery artifacts={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders a MoleculeCard for each image artifact', () => {
    const img1 = makeImageArtifact({ artifactId: 'img-1', data: 'aaa' })
    const img2 = makeImageArtifact({ artifactId: 'img-2', data: 'bbb', title: 'Ibuprofen' })
    render(<ArtifactGallery artifacts={[img1, img2]} />)

    const cards = screen.getAllByTestId('molecule-card')
    expect(cards).toHaveLength(2)
    expect(cards[0]).toHaveAttribute('data-image', 'aaa')
    expect(cards[1]).toHaveAttribute('data-image', 'bbb')
  })

  it('passes title to MoleculeCard', () => {
    render(<ArtifactGallery artifacts={[makeImageArtifact({ title: 'Aspirin' })]} />)
    expect(screen.getByTestId('molecule-card')).toHaveAttribute('data-title', 'Aspirin')
  })

  it('renders an ArtifactRenderer for non-image artifacts', () => {
    render(<ArtifactGallery artifacts={[makeJsonArtifact()]} />)
    expect(screen.queryByTestId('molecule-card')).not.toBeInTheDocument()
    expect(screen.getByTestId('artifact-renderer')).toBeInTheDocument()
    expect(screen.getByTestId('artifact-renderer')).toHaveAttribute('data-artifact-id', 'art-json-1')
  })

  it('renders ArtifactRenderer for text artifacts', () => {
    render(<ArtifactGallery artifacts={[makeTextArtifact()]} />)
    expect(screen.getByTestId('artifact-renderer')).toBeInTheDocument()
  })

  it('renders both MoleculeCard and ArtifactRenderer for mixed artifacts', () => {
    render(<ArtifactGallery artifacts={[makeImageArtifact(), makeJsonArtifact()]} />)
    expect(screen.getByTestId('molecule-card')).toBeInTheDocument()
    expect(screen.getByTestId('artifact-renderer')).toBeInTheDocument()
  })

  it('routes image/jpeg mime-type images to MoleculeCard', () => {
    const jpegArt = makeImageArtifact({ mimeType: 'image/jpeg', artifactId: 'jpeg-1' })
    render(<ArtifactGallery artifacts={[jpegArt]} />)
    expect(screen.getByTestId('molecule-card')).toBeInTheDocument()
    expect(screen.queryByTestId('artifact-renderer')).not.toBeInTheDocument()
  })

  it('routes an image artifact with non-string data to ArtifactRenderer', () => {
    // kind='image' + mimeType='image/png' but data is not a string:
    // should NOT render a MoleculeCard (needs base64 string), but also must NOT
    // be silently dropped — ArtifactRenderer handles it as a fallback.
    const brokenImg: Artifact = {
      artifactId: 'broken-1',
      kind: 'image',
      mimeType: 'image/png',
      data: { nested: 'object' },
      encoding: 'json',
    }
    render(<ArtifactGallery artifacts={[brokenImg]} />)
    expect(screen.queryByTestId('molecule-card')).not.toBeInTheDocument()
    expect(screen.getByTestId('artifact-renderer')).toBeInTheDocument()
    expect(screen.getByTestId('artifact-renderer')).toHaveAttribute('data-artifact-id', 'broken-1')
  })

  it('routes image artifact with non-image mimeType to ArtifactRenderer', () => {
    // kind='image' but mimeType='text/plain' → not excluded from otherArtifacts
    const oddArt: Artifact = {
      artifactId: 'odd-1',
      kind: 'image',
      mimeType: 'text/plain',
      data: 'some text',
      encoding: 'utf8',
    }
    render(<ArtifactGallery artifacts={[oddArt]} />)
    expect(screen.queryByTestId('molecule-card')).not.toBeInTheDocument()
    expect(screen.getByTestId('artifact-renderer')).toBeInTheDocument()
  })

  it('renders multiple non-image artifacts individually', () => {
    const a1 = makeJsonArtifact({ artifactId: 'j1' })
    const a2 = makeTextArtifact({ artifactId: 't1' })
    const a3 = makeTextArtifact({ artifactId: 't2' })
    render(<ArtifactGallery artifacts={[a1, a2, a3]} />)

    const renderers = screen.getAllByTestId('artifact-renderer')
    expect(renderers).toHaveLength(3)
    expect(renderers[0]).toHaveAttribute('data-artifact-id', 'j1')
    expect(renderers[1]).toHaveAttribute('data-artifact-id', 't1')
    expect(renderers[2]).toHaveAttribute('data-artifact-id', 't2')
  })
})

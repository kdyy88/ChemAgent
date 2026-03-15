'use client'

import { MoleculeCard } from './MoleculeCard'
import { ArtifactRenderer } from './ArtifactRenderer'
import type { Artifact } from '@/lib/types'

interface ArtifactGalleryProps {
  artifacts: Artifact[]
}

/**
 * Renders a set of artifacts with smart layout:
 *   Images → flex-wrap row: cards are 160 px wide, fill the row left-to-right,
 *            wrap only when there is no more horizontal space.
 * Non-image artifacts render below as individual cards.
 */
export function ArtifactGallery({ artifacts }: ArtifactGalleryProps) {
  if (artifacts.length === 0) return null

  const imageArtifacts = artifacts.filter(
    (a) =>
      a.kind === 'image' &&
      a.mimeType.startsWith('image/') &&
      typeof a.data === 'string',
  )
  const otherArtifacts = artifacts.filter(
    (a) => !(a.kind === 'image' && a.mimeType.startsWith('image/')),
  )

  return (
    <div className="flex flex-col gap-3 mt-1">
      {imageArtifacts.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {imageArtifacts.map((artifact) => (
            <MoleculeCard
              key={artifact.artifactId}
              image={artifact.data as string}
              title={artifact.title}
            />
          ))}
        </div>
      )}

      {otherArtifacts.map((artifact) => (
        <ArtifactRenderer key={artifact.artifactId} artifact={artifact} />
      ))}
    </div>
  )
}

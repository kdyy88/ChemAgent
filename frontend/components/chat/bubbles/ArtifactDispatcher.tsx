import { ImageArtifact } from './ImageArtifact'
import { TextArtifact, type TextArtifactEvent } from './TextArtifact'
import type { MoleculeImageArtifact, SSEArtifactEvent } from '@/lib/sse-types'

interface ArtifactDispatcherProps {
  artifacts: SSEArtifactEvent[]
}

function isImageArtifact(artifact: SSEArtifactEvent): artifact is MoleculeImageArtifact {
  return (
    artifact.kind === 'molecule_image' ||
    artifact.kind === 'descriptor_structure_image' ||
    artifact.kind === 'highlighted_substructure'
  )
}

export function ArtifactDispatcher({ artifacts }: ArtifactDispatcherProps) {
  if (artifacts.length === 0) return null

  return (
    <div className="flex flex-row flex-wrap items-start gap-3 mt-1">
      {artifacts.map((artifact, index) => (
        isImageArtifact(artifact) ?
          <ImageArtifact key={`${artifact.turn_id}-${index}`} artifact={artifact} />
        : (
            <div key={`${artifact.turn_id}-${index}`} className="w-full">
              <TextArtifact artifact={artifact as TextArtifactEvent} />
            </div>
          )
      ))}
    </div>
  )
}
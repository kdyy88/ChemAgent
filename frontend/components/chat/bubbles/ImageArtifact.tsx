import { MoleculeCard } from '@/components/chat/MoleculeCard'
import type { MoleculeImageArtifact } from '@/lib/sse-types'

interface ImageArtifactProps {
  artifact: MoleculeImageArtifact
}

export function ImageArtifact({ artifact }: ImageArtifactProps) {
  return (
    <div className="w-[196px] shrink-0">
      <MoleculeCard image={artifact.image} title={artifact.title} />
    </div>
  )
}
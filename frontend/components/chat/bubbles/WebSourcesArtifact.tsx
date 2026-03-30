'use client'

import { Globe } from 'lucide-react'
import { Source, SourceContent, SourceTrigger } from '@/components/ui/source'
import type { WebSearchSourcesArtifact } from '@/lib/sse-types'

interface WebSourcesArtifactProps {
  artifact: WebSearchSourcesArtifact
}

export function WebSourcesArtifact({ artifact }: WebSourcesArtifactProps) {
  if (!artifact.sources || artifact.sources.length === 0) return null

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/60 px-0.5">
        <Globe className="h-3 w-3" aria-hidden="true" />
        <span>来源 · {artifact.sources.length} 个结果</span>
        {artifact.query && (
          <span className="truncate max-w-[200px] text-muted-foreground/40">"{artifact.query}"</span>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {artifact.sources.map((src, i) => (
          <Source key={`${src.url}-${i}`} href={src.url}>
            <SourceTrigger
              label={i + 1}
              showFavicon
              className="gap-1.5 pr-2"
            />
            <SourceContent
              title={src.title || src.url}
              description={src.snippet}
            />
          </Source>
        ))}
      </div>
    </div>
  )
}

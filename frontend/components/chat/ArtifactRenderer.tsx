'use client'

import { useEffect, useMemo } from 'react'
import { Download, FileJson, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { MoleculeCard } from './MoleculeCard'
import type { Artifact } from '@/lib/types'

interface ArtifactRendererProps {
  artifact: Artifact
}

function useObjectUrl(content: BlobPart, mimeType: string) {
  const blob = useMemo(() => new Blob([content], { type: mimeType }), [content, mimeType])
  const url = useMemo(() => URL.createObjectURL(blob), [blob])

  useEffect(() => () => URL.revokeObjectURL(url), [url])

  return url
}

function JsonArtifactCard({ artifact }: ArtifactRendererProps) {
  const jsonText = JSON.stringify(artifact.data, null, 2)
  const url = useObjectUrl(jsonText, 'application/json')

  return (
    <Card className="max-w-[420px] shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <FileJson className="h-4 w-4" />
          {artifact.title ?? 'JSON Artifact'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <pre className="max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs">{jsonText}</pre>
      </CardContent>
      <CardFooter>
        <a href={url} download={`${artifact.artifactId ?? 'artifact'}.json`} className="contents">
          <Button variant="outline" size="sm" className="flex items-center gap-1.5">
            <Download className="h-3.5 w-3.5" />
            Download JSON
          </Button>
        </a>
      </CardFooter>
    </Card>
  )
}

function TextArtifactCard({ artifact }: ArtifactRendererProps) {
  const text = typeof artifact.data === 'string' ? artifact.data : JSON.stringify(artifact.data, null, 2)
  const url = useObjectUrl(text, artifact.mimeType || 'text/plain')

  return (
    <Card className="max-w-[420px] shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <FileText className="h-4 w-4" />
          {artifact.title ?? 'Artifact'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">{text}</pre>
      </CardContent>
      <CardFooter>
        <a href={url} download={`${artifact.artifactId ?? 'artifact'}.txt`} className="contents">
          <Button variant="outline" size="sm" className="flex items-center gap-1.5">
            <Download className="h-3.5 w-3.5" />
            Download
          </Button>
        </a>
      </CardFooter>
    </Card>
  )
}

export function ArtifactRenderer({ artifact }: ArtifactRendererProps) {
  if (artifact.kind === 'image' && artifact.mimeType.startsWith('image/') && typeof artifact.data === 'string') {
    return <MoleculeCard image={artifact.data} title={artifact.title} />
  }

  if (artifact.encoding === 'json' || artifact.mimeType === 'application/json') {
    return <JsonArtifactCard artifact={artifact} />
  }

  return <TextArtifactCard artifact={artifact} />
}

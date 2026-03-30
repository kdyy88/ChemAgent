'use client'

import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type {
  ConformerSdfArtifact,
  FormatConversionArtifact,
  PdbqtFileArtifact,
} from '@/lib/sse-types'

export type TextArtifactEvent =
  | ConformerSdfArtifact
  | PdbqtFileArtifact
  | FormatConversionArtifact

interface TextArtifactProps {
  artifact: TextArtifactEvent
}

export function TextArtifact({ artifact }: TextArtifactProps) {
  const ext =
    artifact.kind === 'pdbqt_file' ? 'pdbqt'
    : artifact.kind === 'conformer_sdf' ? 'sdf'
    : 'txt'

  const content =
    artifact.kind === 'conformer_sdf' ? artifact.sdf_content
    : artifact.kind === 'pdbqt_file' ? artifact.pdbqt_content
    : artifact.output

  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${artifact.title ?? artifact.kind}.${ext}`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="rounded-xl border bg-muted/40 overflow-hidden text-sm">
      <div className="flex items-center justify-between px-3 py-2 border-b bg-muted/60">
        <span className="font-medium text-muted-foreground truncate">
          {artifact.title ?? artifact.kind}
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 px-2 gap-1 text-xs"
          onClick={handleDownload}
        >
          <Download className="h-3.5 w-3.5" />
          .{ext}
        </Button>
      </div>
      <pre className="p-3 text-xs leading-relaxed overflow-auto max-h-48 font-mono whitespace-pre-wrap break-all">
        {content.slice(0, 2000)}
        {content.length > 2000 && '\n…（已截断）'}
      </pre>
    </div>
  )
}
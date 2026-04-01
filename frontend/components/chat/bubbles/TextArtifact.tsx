'use client'

import { FileDown } from 'lucide-react'
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

function getExt(artifact: TextArtifactEvent): string {
  if (artifact.kind === 'pdbqt_file') return 'pdbqt'
  if (artifact.kind === 'conformer_sdf') return 'sdf'
  // format_conversion: use output_format if available (e.g. mol2, xyz, pdb)
  if (artifact.kind === 'format_conversion' && artifact.output_format) {
    return artifact.output_format.toLowerCase()
  }
  return 'txt'
}

function getContent(artifact: TextArtifactEvent): string {
  if (artifact.kind === 'conformer_sdf') return artifact.sdf_content
  if (artifact.kind === 'pdbqt_file') return artifact.pdbqt_content
  return artifact.output
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function TextArtifact({ artifact }: TextArtifactProps) {
  const ext = getExt(artifact)
  const content = getContent(artifact)
  const title = artifact.title ?? artifact.kind
  const sizeLabel = formatBytes(new TextEncoder().encode(content).length)

  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${title}.${ext}`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex items-center gap-3 rounded-xl border bg-muted/40 px-4 py-3 text-sm hover:bg-muted/60 transition-colors">
      {/* File type badge */}
      <div className="flex-shrink-0 flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary">
        <FileDown className="h-5 w-5" />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="font-medium truncate leading-tight">{title}</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          .{ext.toUpperCase()} · {sizeLabel}
        </p>
      </div>

      {/* Download */}
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="flex-shrink-0 gap-1.5 text-xs h-8 px-3"
        onClick={handleDownload}
        aria-label={`下载 ${title}.${ext}`}
      >
        <FileDown className="h-3.5 w-3.5" aria-hidden="true" />
        下载
      </Button>
    </div>
  )
}
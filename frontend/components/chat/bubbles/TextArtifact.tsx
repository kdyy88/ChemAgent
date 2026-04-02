'use client'

import { useState } from 'react'
import { FileDown, Maximize2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Mol3DViewerGuard } from '@/components/agent/viewers/Mol3DViewerGuard'
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
  const [modalOpen, setModalOpen] = useState(false)

  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${title}.${ext}`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const is3D = artifact.kind === 'conformer_sdf' || artifact.kind === 'pdbqt_file'
  const viewer3DData = is3D
    ? artifact.kind === 'conformer_sdf'
      ? (artifact as ConformerSdfArtifact).sdf_content
      : (artifact as PdbqtFileArtifact).pdbqt_content
    : null
  const viewer3DFormat = artifact.kind === 'pdbqt_file' ? 'pdbqt' : 'sdf'

  return (
    <>
      <div className="flex flex-col rounded-xl border bg-muted/40 text-sm overflow-hidden" style={{ height: is3D ? 360 : undefined }}>
        {/* Header row: icon + info + actions */}
        <div className="flex items-center gap-3 px-4 py-3 hover:bg-muted/60 transition-colors flex-shrink-0">
          <div className="flex-shrink-0 flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary">
            <FileDown className="h-5 w-5" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-medium truncate leading-tight">{title}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              .{ext.toUpperCase()} · {sizeLabel}
            </p>
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {is3D && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="gap-1.5 text-xs h-8 px-3"
                onClick={() => setModalOpen(true)}
                aria-label={`放大预览 ${title}`}
              >
                <Maximize2 className="h-3.5 w-3.5" aria-hidden="true" />
                预览
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="gap-1.5 text-xs h-8 px-3"
              onClick={handleDownload}
              aria-label={`下载 ${title}.${ext}`}
            >
              <FileDown className="h-3.5 w-3.5" aria-hidden="true" />
              下载
            </Button>
          </div>
        </div>

        {/* 3D viewer – suspended while dialog is open to free WebGL context */}
        {is3D && viewer3DData && !modalOpen && (
          <Mol3DViewerGuard
            data={viewer3DData}
            format={viewer3DFormat as 'sdf' | 'pdbqt'}
            size="compact"
            className="flex-1 h-0"
          />
        )}
        {/* placeholder keeps card height stable when viewer is suspended */}
        {is3D && modalOpen && <div className="flex-1 h-0 bg-muted/20" />}
      </div>

      {/* Fullscreen preview dialog – fixed 1024×768 */}
      {is3D && viewer3DData && (
        <Dialog open={modalOpen} onOpenChange={setModalOpen}>
          <DialogContent
            className="p-0 overflow-hidden gap-0 flex flex-col"
            style={{ width: 1024, maxWidth: 1024, height: 768 }}
          >
            <DialogHeader className="px-5 py-3 border-b bg-muted/30 flex-shrink-0">
              <DialogTitle className="text-sm font-medium flex items-center gap-2">
                <span>{title}</span>
                <span className="text-xs font-normal text-muted-foreground">
                  .{ext.toUpperCase()} · {sizeLabel}
                </span>
              </DialogTitle>
            </DialogHeader>
            {/* viewer fills remaining 720px */}
            <div className="flex-1 min-h-0">
              <Mol3DViewerGuard
                data={viewer3DData}
                format={viewer3DFormat as 'sdf' | 'pdbqt'}
                size="full"
                className="h-full"
              />
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
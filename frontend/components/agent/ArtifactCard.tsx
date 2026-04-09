'use client'

import { Download, ExternalLink, ChevronDown } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Mol3DViewerGuard } from '@/components/agent/viewers/Mol3DViewerGuard'
import type { SSEArtifactEvent } from '@/lib/sse-types'

// ── Download helper ────────────────────────────────────────────────────────────

function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── Kind-specific renderers ────────────────────────────────────────────────────

function MoleculeImageRenderer({ artifact }: { artifact: Extract<SSEArtifactEvent, { kind: 'molecule_image' | 'descriptor_structure_image' | 'highlighted_substructure' }> }) {
  return (
    <div className="flex flex-col gap-2">
      <img
        src={`data:image/png;base64,${artifact.image}`}
        alt={artifact.title}
        className="w-full rounded-md border border-border/50 bg-white object-contain"
        style={{ maxHeight: 220 }}
      />
      {artifact.smiles && (
        <p className="font-mono text-[10px] text-muted-foreground break-all leading-tight">
          {artifact.smiles}
        </p>
      )}
    </div>
  )
}

function SdfRenderer({ artifact }: { artifact: Extract<SSEArtifactEvent, { kind: 'conformer_sdf' }> }) {
  return (
    <div className="flex flex-col gap-2">
      {/* Interactive 3D viewer */}
      <Mol3DViewerGuard data={artifact.sdf_content} format="sdf" size="full" />

      {artifact.energy !== undefined && (
        <p className="text-xs text-muted-foreground">
          Energy: <span className="font-mono">{artifact.energy.toFixed(4)} kcal/mol</span>
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          className="h-7 gap-1.5 text-xs"
          onClick={() => downloadText(`${artifact.title.replace(/\s+/g, '_')}.sdf`, artifact.sdf_content)}
        >
          <Download className="h-3 w-3" />
          Download SDF
        </Button>
      </div>

      {/* Raw text — collapsed by default */}
      <details className="group">
        <summary className="flex cursor-pointer select-none items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground">
          <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
          原始 SDF
        </summary>
        <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-muted/60 p-2 text-[10px] font-mono leading-relaxed text-foreground/80">
          {artifact.sdf_content.slice(0, 800)}{artifact.sdf_content.length > 800 ? '\n…' : ''}
        </pre>
      </details>
    </div>
  )
}

function PdbqtRenderer({ artifact }: { artifact: Extract<SSEArtifactEvent, { kind: 'pdbqt_file' }> }) {
  return (
    <div className="flex flex-col gap-2">
      {/* Interactive 3D viewer */}
      <Mol3DViewerGuard data={artifact.pdbqt_content} format="pdbqt" size="full" />

      {artifact.rotatable_bonds !== undefined && (
        <p className="text-xs text-muted-foreground">
          Rotatable bonds: <span className="font-mono">{artifact.rotatable_bonds}</span>
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          className="h-7 gap-1.5 text-xs"
          onClick={() => downloadText(`${artifact.title.replace(/\s+/g, '_')}.pdbqt`, artifact.pdbqt_content)}
        >
          <Download className="h-3 w-3" />
          Download PDBQT
        </Button>
      </div>

      {/* Raw text — collapsed by default */}
      <details className="group">
        <summary className="flex cursor-pointer select-none items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground">
          <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
          原始 PDBQT
        </summary>
        <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-muted/60 p-2 text-[10px] font-mono leading-relaxed text-foreground/80">
          {artifact.pdbqt_content.slice(0, 800)}{artifact.pdbqt_content.length > 800 ? '\n…' : ''}
        </pre>
      </details>
    </div>
  )
}

function FormatConversionRenderer({ artifact }: { artifact: Extract<SSEArtifactEvent, { kind: 'format_conversion' }> }) {
  return (
    <div className="flex flex-col gap-2">
      {artifact.input_format && artifact.output_format && (
        <p className="text-xs text-muted-foreground">
          <span className="font-mono uppercase">{artifact.input_format}</span>
          {' → '}
          <span className="font-mono uppercase">{artifact.output_format}</span>
        </p>
      )}
      <pre className="max-h-48 overflow-auto rounded-md bg-muted/60 p-2 text-[10px] font-mono leading-relaxed text-foreground/80">
        {artifact.output.slice(0, 1000)}{artifact.output.length > 1000 ? '\n…' : ''}
      </pre>
      <Button
        size="sm"
        variant="outline"
        className="h-7 gap-1.5 text-xs self-start"
        onClick={() => downloadText(`converted.${artifact.output_format ?? 'txt'}`, artifact.output)}
      >
        <Download className="h-3 w-3" />
        Download
      </Button>
    </div>
  )
}

function WebSearchRenderer({ artifact }: { artifact: Extract<SSEArtifactEvent, { kind: 'web_search_sources' }> }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">
        Query: <span className="italic">{artifact.query}</span>
      </p>
      <ul className="flex flex-col gap-1.5">
        {artifact.sources.map((s, i) => (
          <li key={i} className="rounded-md border border-border/60 bg-muted/30 p-2">
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-1.5 text-xs font-medium text-primary hover:underline"
            >
              <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
              {s.title}
            </a>
            {s.snippet && (
              <p className="mt-1 text-[10px] text-muted-foreground line-clamp-2">{s.snippet}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ── Kind badge colours ─────────────────────────────────────────────────────────

const KIND_BADGE: Record<string, string> = {
  molecule_image:              'bg-primary/10 text-primary border-primary/20',
  descriptor_structure_image:  'bg-primary/10 text-primary border-primary/20',
  highlighted_substructure:    'bg-amber-500/10 text-amber-600 border-amber-500/20 dark:text-amber-400',
  conformer_sdf:               'bg-violet-500/10 text-violet-600 border-violet-500/20 dark:text-violet-400',
  pdbqt_file:                  'bg-rose-500/10 text-rose-600 border-rose-500/20 dark:text-rose-400',
  format_conversion:           'bg-sky-500/10 text-sky-600 border-sky-500/20 dark:text-sky-400',
  web_search_sources:          'bg-emerald-500/10 text-emerald-600 border-emerald-500/20 dark:text-emerald-400',
}

// ── Public component ───────────────────────────────────────────────────────────

export function ArtifactCard({ artifact }: { artifact: SSEArtifactEvent }) {
  const badgeCls = KIND_BADGE[artifact.kind] ?? 'bg-muted text-muted-foreground'

  return (
    <Card className="overflow-hidden border-border/60 bg-card/80 shadow-sm backdrop-blur transition-shadow hover:shadow-md">
      <CardHeader className="flex flex-row items-start justify-between gap-2 pb-2 pt-3 px-3">
        <CardTitle className="text-xs font-semibold leading-snug">
          {'title' in artifact ? artifact.title : artifact.query}
        </CardTitle>
        <Badge variant="outline" className={`shrink-0 text-[10px] px-1.5 py-0 h-5 ${badgeCls}`}>
          {artifact.kind.replace(/_/g, ' ')}
        </Badge>
      </CardHeader>
      <CardContent className="px-3 pb-3 pt-0">
        {(artifact.kind === 'molecule_image' ||
          artifact.kind === 'descriptor_structure_image' ||
          artifact.kind === 'highlighted_substructure') && (
          <MoleculeImageRenderer artifact={artifact as Parameters<typeof MoleculeImageRenderer>[0]['artifact']} />
        )}
        {artifact.kind === 'conformer_sdf' && (
          <SdfRenderer artifact={artifact as Parameters<typeof SdfRenderer>[0]['artifact']} />
        )}
        {artifact.kind === 'pdbqt_file' && (
          <PdbqtRenderer artifact={artifact as Parameters<typeof PdbqtRenderer>[0]['artifact']} />
        )}
        {artifact.kind === 'format_conversion' && (
          <FormatConversionRenderer artifact={artifact as Parameters<typeof FormatConversionRenderer>[0]['artifact']} />
        )}
        {artifact.kind === 'web_search_sources' && (
          <WebSearchRenderer artifact={artifact as Parameters<typeof WebSearchRenderer>[0]['artifact']} />
        )}
      </CardContent>
    </Card>
  )
}

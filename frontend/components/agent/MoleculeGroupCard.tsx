'use client'

import { Download } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Mol3DViewerGuard } from '@/components/agent/viewers/Mol3DViewerGuard'
import type { SSEArtifactEvent, MoleculeImageArtifact, ConformerSdfArtifact, PdbqtFileArtifact } from '@/lib/sse-types'

type MolGroup = {
  smiles: string
  artifacts: SSEArtifactEvent[]
  firstIndex: number
}

function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── Helpers to pick the best artifact per visual type ─────────────────────────

function pickImage(artifacts: SSEArtifactEvent[]): MoleculeImageArtifact | undefined {
  // Prefer highlighted_substructure > descriptor_structure_image > molecule_image
  const order = ['highlighted_substructure', 'descriptor_structure_image', 'molecule_image']
  for (const kind of order) {
    const found = artifacts.find((a) => a.kind === kind) as MoleculeImageArtifact | undefined
    if (found) return found
  }
  return undefined
}

function pickSdf(artifacts: SSEArtifactEvent[]): ConformerSdfArtifact | undefined {
  return artifacts.find((a) => a.kind === 'conformer_sdf') as ConformerSdfArtifact | undefined
}

function pickPdbqt(artifacts: SSEArtifactEvent[]): PdbqtFileArtifact | undefined {
  return artifacts.find((a) => a.kind === 'pdbqt_file') as PdbqtFileArtifact | undefined
}

// ── Sub-renderers ──────────────────────────────────────────────────────────────

function Image2DTab({ artifact }: { artifact: MoleculeImageArtifact }) {
  return (
    <div className="flex flex-col gap-2">
      <img
        src={`data:image/png;base64,${artifact.image}`}
        alt={artifact.title}
        className="w-full rounded-md border border-border/50 bg-white object-contain"
        style={{ maxHeight: 220 }}
      />
      {artifact.highlight_atoms && artifact.highlight_atoms.length > 0 && (
        <p className="text-[10px] text-muted-foreground">
          高亮原子索引：{artifact.highlight_atoms.join(', ')}
        </p>
      )}
    </div>
  )
}

function Conformer3DTab({ artifact }: { artifact: ConformerSdfArtifact }) {
  return (
    <div className="flex flex-col gap-2">
      <Mol3DViewerGuard data={artifact.sdf_content} format="sdf" size="full" />
      {artifact.energy !== undefined && (
        <p className="text-xs text-muted-foreground">
          Energy: <span className="font-mono">{artifact.energy.toFixed(4)} kcal/mol</span>
        </p>
      )}
      <Button
        size="sm"
        variant="outline"
        className="h-7 gap-1.5 self-start text-xs"
        onClick={() => downloadText(`${artifact.title.replace(/\s+/g, '_')}.sdf`, artifact.sdf_content)}
      >
        <Download className="h-3 w-3" />
        Download SDF
      </Button>
    </div>
  )
}

function PdbqtTab({ artifact }: { artifact: PdbqtFileArtifact }) {
  return (
    <div className="flex flex-col gap-2">
      <Mol3DViewerGuard data={artifact.pdbqt_content} format="pdbqt" size="full" />
      {artifact.rotatable_bonds !== undefined && (
        <p className="text-xs text-muted-foreground">
          Rotatable bonds: <span className="font-mono">{artifact.rotatable_bonds}</span>
        </p>
      )}
      <Button
        size="sm"
        variant="outline"
        className="h-7 gap-1.5 self-start text-xs"
        onClick={() => downloadText(`${artifact.title.replace(/\s+/g, '_')}.pdbqt`, artifact.pdbqt_content)}
      >
        <Download className="h-3 w-3" />
        Download PDBQT
      </Button>
    </div>
  )
}

// ── Public component ───────────────────────────────────────────────────────────

export function MoleculeGroupCard({ group }: { group: MolGroup }) {
  const image2d = pickImage(group.artifacts)
  const conformer = pickSdf(group.artifacts)
  const pdbqt = pickPdbqt(group.artifacts)

  // Derive card title from the first artifact that has one
  const title =
    (group.artifacts.find((a) => 'title' in a) as { title: string } | undefined)?.title ??
    group.smiles.slice(0, 40)

  // Build tab list only for available data
  const tabs: Array<{ value: string; label: string }> = []
  if (image2d) tabs.push({ value: '2d', label: '2D 结构' })
  if (conformer) tabs.push({ value: '3d', label: '3D 构象' })
  if (pdbqt) tabs.push({ value: 'pdbqt', label: 'PDBQT' })

  const defaultTab = tabs[0]?.value ?? '2d'

  return (
    <Card className="overflow-hidden border-border/60 bg-card/80 shadow-sm backdrop-blur transition-shadow hover:shadow-md">
      <CardHeader className="flex flex-row items-start justify-between gap-2 pb-2 pt-3 px-3">
        <CardTitle className="text-xs font-semibold leading-snug line-clamp-2">{title}</CardTitle>
        <Badge
          variant="outline"
          className="shrink-0 text-[10px] px-1.5 py-0 h-5 bg-primary/10 text-primary border-primary/20"
        >
          molecule
        </Badge>
      </CardHeader>

      <CardContent className="px-3 pb-3 pt-0">
        {/* SMILES */}
        <p className="mb-2 font-mono text-[10px] text-muted-foreground break-all leading-tight">
          {group.smiles}
        </p>

        {tabs.length <= 1 ? (
          // No need for tabs if only one view available
          <>
            {image2d && <Image2DTab artifact={image2d} />}
            {!image2d && conformer && <Conformer3DTab artifact={conformer} />}
            {!image2d && !conformer && pdbqt && <PdbqtTab artifact={pdbqt} />}
          </>
        ) : (
          <Tabs defaultValue={defaultTab}>
            <TabsList className="mb-2 h-7 gap-1 p-0.5">
              {tabs.map((t) => (
                <TabsTrigger key={t.value} value={t.value} className="h-6 px-2 text-[11px]">
                  {t.label}
                </TabsTrigger>
              ))}
            </TabsList>

            {image2d && (
              <TabsContent value="2d" className="mt-0">
                <Image2DTab artifact={image2d} />
              </TabsContent>
            )}
            {conformer && (
              <TabsContent value="3d" className="mt-0">
                <Conformer3DTab artifact={conformer} />
              </TabsContent>
            )}
            {pdbqt && (
              <TabsContent value="pdbqt" className="mt-0">
                <PdbqtTab artifact={pdbqt} />
              </TabsContent>
            )}
          </Tabs>
        )}
      </CardContent>
    </Card>
  )
}

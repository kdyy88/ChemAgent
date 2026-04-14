'use client'

import { ImageOff } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { useSseStore } from '@/store/sseStore'
import { ArtifactCard } from './ArtifactCard'
import { MoleculeGroupCard } from './MoleculeGroupCard'
import type { SSEArtifactEvent } from '@/lib/sse-types'

// Artifact kinds that belong to a molecule and can be grouped by SMILES.
const MOL_KINDS = new Set([
  'molecule_image',
  'descriptor_structure_image',
  'highlighted_substructure',
  'conformer_sdf',
  'pdbqt_file',
])

type MolGroup = {
  smiles: string
  artifacts: SSEArtifactEvent[]
  firstIndex: number
}

type CanvasItem =
  | { type: 'group'; group: MolGroup; index: number }
  | { type: 'single'; artifact: SSEArtifactEvent; index: number }

/**
 * Group consecutive/non-consecutive artifacts that share the same SMILES and
 * are molecule-related into a single MoleculeGroupCard.  All other artifacts
 * render as individual ArtifactCards, preserving their original chronological
 * position (first appearance of each SMILES group).
 */
function groupArtifacts(artifacts: SSEArtifactEvent[]): CanvasItem[] {
  const groups = new Map<string, MolGroup>()
  const order: CanvasItem[] = []

  artifacts.forEach((artifact, i) => {
    const smiles = 'smiles' in artifact && artifact.smiles && MOL_KINDS.has(artifact.kind)
      ? artifact.smiles
      : null

    if (smiles) {
      if (!groups.has(smiles)) {
        const group: MolGroup = { smiles, artifacts: [artifact], firstIndex: i }
        groups.set(smiles, group)
        order.push({ type: 'group', group, index: i })
      } else {
        groups.get(smiles)!.artifacts.push(artifact)
      }
    } else {
      order.push({ type: 'single', artifact, index: i })
    }
  })

  return order
}

export function ArtifactCanvas() {
  const turns = useSseStore((s) => s.turns)

  // Collect all artifacts across all turns, keeping chronological order.
  const artifacts: SSEArtifactEvent[] = turns.flatMap((t) => t.artifacts)
  const items = groupArtifacts(artifacts)

  // For the header count show unique molecule groups + ungrouped artifacts
  const displayCount = items.length

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background">
      {/* ── Header bar ── */}
      <div className="shrink-0 flex items-center gap-2.5 border-b border-border/70 bg-background/80 px-4 h-11 backdrop-blur-sm">
        <span className="text-[11px] font-semibold tracking-[0.08em] text-muted-foreground/60 uppercase">
          Artifact Canvas
        </span>
        {displayCount > 0 && (
          <span className="ml-auto text-[11px] text-muted-foreground/50 tabular-nums font-medium">
            {displayCount} result{displayCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* ── Canvas body ── */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {items.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center select-none">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-border/50 bg-muted/30 text-muted-foreground/30">
              <ImageOff className="h-5 w-5" />
            </div>
            <div className="space-y-1">
              <p className="text-[13px] font-medium text-muted-foreground/60">
                Agent 执行结果将在这里展示
              </p>
              <p className="text-[11px] text-muted-foreground/35">
                Molecule images · SDF files · Search results
              </p>
            </div>
          </div>
        ) : (
          <div className="columns-1 gap-3 sm:columns-2 xl:columns-3">
            <AnimatePresence initial={false}>
              {items.map((item) => (
                <motion.div
                  key={item.type === 'group' ? `group-${item.group.smiles}` : `single-${item.index}`}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, delay: 0.03 * Math.min(item.index, 8) }}
                  className="mb-3 break-inside-avoid"
                >
                  {item.type === 'group' ? (
                    <MoleculeGroupCard group={item.group} />
                  ) : (
                    <ArtifactCard artifact={item.artifact} />
                  )}
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  )
}

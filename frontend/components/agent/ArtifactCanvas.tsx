'use client'

import { ImageOff } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { useSseStore } from '@/store/sseStore'
import { ArtifactCard } from './ArtifactCard'
import type { SSEArtifactEvent } from '@/lib/sse-types'

export function ArtifactCanvas() {
  const turns = useSseStore((s) => s.turns)

  // Collect all artifacts across all turns, keeping chronological order.
  const artifacts: SSEArtifactEvent[] = turns.flatMap((t) => t.artifacts)

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* ── Header bar ── */}
      <div className="shrink-0 flex items-center gap-2 border-b bg-background/80 px-4 py-2.5 backdrop-blur">
        <span className="text-xs font-semibold tracking-tight text-foreground/80 uppercase">
          Artifact Canvas
        </span>
        {artifacts.length > 0 && (
          <span className="ml-auto text-xs text-muted-foreground tabular-nums">
            {artifacts.length} result{artifacts.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* ── Canvas body ── */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {artifacts.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center select-none">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-dashed border-border/60 text-muted-foreground/40">
              <ImageOff className="h-6 w-6" />
            </div>
            <p className="text-sm text-muted-foreground/60">
              Agent 执行结果将在这里展示
            </p>
            <p className="text-xs text-muted-foreground/40">
              Molecule images, SDF files, search results…
            </p>
          </div>
        ) : (
          <div className="columns-1 gap-3 sm:columns-2 xl:columns-3">
            <AnimatePresence initial={false}>
              {artifacts.map((artifact, i) => (
                <motion.div
                  key={`${artifact.turn_id}-${i}`}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, delay: 0.03 * Math.min(i, 8) }}
                  className="mb-3 break-inside-avoid"
                >
                  <ArtifactCard artifact={artifact} />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  )
}

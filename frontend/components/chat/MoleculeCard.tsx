'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import { Download, Maximize2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface MoleculeCardProps {
  image: string // base64 PNG
  title?: string | null
}

export function MoleculeCard({ image, title }: MoleculeCardProps) {
  const [open, setOpen] = useState(false)
  const dataUrl = `data:image/png;base64,${image}`

  return (
    <>
      {/* ── Thumbnail ─────────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 6 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: 'spring', stiffness: 340, damping: 24, mass: 0.8 }}
        className="flex flex-col items-center gap-1 w-full"
      >
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="group relative w-full aspect-square rounded-xl border bg-card overflow-hidden shadow-sm hover:shadow-md transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`View full size: ${title ?? 'molecule'}`}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={dataUrl}
            alt={title ?? 'Molecule structure'}
            className="w-full h-full object-contain"
          />
          {/* hover overlay */}
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/20 transition-colors">
            <Maximize2 className="h-4 w-4 text-white opacity-0 group-hover:opacity-100 drop-shadow transition-opacity" />
          </div>
        </button>
        {title && (
          <span className="w-full truncate text-center text-[10px] text-muted-foreground leading-tight">
            {title}
          </span>
        )}
      </motion.div>

      {/* ── Full-size modal ───────────────────────────────────────────── */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl p-0 overflow-hidden">
          <DialogHeader className="px-5 pt-5 pb-0">
            <DialogTitle className="text-sm font-medium">
              {title ?? 'Molecule Structure'}
            </DialogTitle>
          </DialogHeader>
          <div className="px-5 py-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={dataUrl}
              alt={title ?? 'Molecule structure'}
              className="w-full h-auto rounded-lg border"
            />
          </div>
          <div className="flex justify-end gap-2 px-5 pb-5">
            <a href={dataUrl} download={`${title ?? 'molecule'}.png`} className="contents">
              <Button variant="outline" size="sm" className="gap-1.5">
                <Download className="h-3.5 w-3.5" />
                Download PNG
              </Button>
            </a>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)} className="gap-1.5">
              <X className="h-3.5 w-3.5" />
              Close
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

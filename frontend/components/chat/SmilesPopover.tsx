'use client'

import { useEffect, useRef } from 'react'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { cn } from '@/lib/utils'

interface SmilesPopoverProps {
  smiles: string
  children: React.ReactNode
  className?: string
}

/**
 * Wraps any element with a hover card that renders the SMILES string
 * as a 2D molecular structure using SmilesDrawer (canvas-based, no WASM).
 */
export function SmilesPopover({ smiles, children, className }: SmilesPopoverProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    let cancelled = false

    async function draw() {
      if (!canvasRef.current || !smiles) return
      try {
        // Dynamic import to avoid SSR
        const SD = await import('smiles-drawer')
        if (cancelled) return
        // Use Drawer (canvas) API
        const drawer = new SD.default.Drawer({ width: 180, height: 180, bondThickness: 1.2, fontSizeLarge: 6 })
        SD.default.parse(smiles, (tree: unknown) => {
          if (!cancelled && canvasRef.current) {
            drawer.draw(tree, canvasRef.current, 'light', false)
          }
        }, () => {
          // Parse error — silently ignore invalid SMILES
        })
      } catch {
        // Import or draw error — silently ignore
      }
    }

    draw()
    return () => { cancelled = true }
  }, [smiles])

  return (
    <HoverCard openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>
        <span
          className={cn(
            'cursor-help rounded-sm px-1 font-mono text-sm',
            'bg-primary/10 text-primary border border-primary/20',
            'hover:bg-primary/20 transition-colors',
            className,
          )}
        >
          {children}
        </span>
      </HoverCardTrigger>
      <HoverCardContent
        side="top"
        className="w-[204px] p-2 flex flex-col items-center gap-1.5 shadow-xl"
      >
        <canvas
          ref={canvasRef}
          width={180}
          height={180}
          className="rounded border bg-white"
          aria-label={`2D structure: ${smiles}`}
        />
        <p className="text-[9px] font-mono text-muted-foreground text-center break-all leading-tight max-w-full">
          {smiles.length > 40 ? smiles.slice(0, 40) + '…' : smiles}
        </p>
      </HoverCardContent>
    </HoverCard>
  )
}

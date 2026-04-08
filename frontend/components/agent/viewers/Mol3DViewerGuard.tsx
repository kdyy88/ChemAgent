'use client'

import { useEffect, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { Skeleton } from '@/components/ui/skeleton'
import type { Molecule3DViewerProps } from './Molecule3DViewer'

// Lazy-load the WebGL component — keeps 3dmol (~2MB) out of the initial bundle
const Molecule3DViewer = dynamic<Molecule3DViewerProps>(
  () => import('./Molecule3DViewer').then(m => ({ default: m.Molecule3DViewer })),
  { ssr: false, loading: () => null }
)

type Mol3DViewerGuardProps = Molecule3DViewerProps & {
  /** Override the pixel height. Falls back to size preset: compact=192, full=288 */
  height?: number
  /** Extra classes for the sentinel div (e.g. 'flex-1 h-0' to fill a flex parent) */
  className?: string
}

/**
 * Guards the 3D viewer behind an IntersectionObserver.
 *
 * Strategy: **conditional unmount** (not just clear())
 * - When the sentinel div enters the viewport → mount <Molecule3DViewer>
 * - When it leaves → unmount it entirely, React removes the canvas from the DOM,
 *   the browser's GC reclaims the WebGL context and GPU memory.
 *
 * This prevents context overflow when many artifact cards are rendered at once.
 */
export function Mol3DViewerGuard({ data, format, size = 'full', height: heightProp, className }: Mol3DViewerGuardProps) {
  const sentinelRef = useRef<HTMLDivElement>(null)
  // Start as true so elements that are already in the viewport on mount never
  // show a Skeleton flash.  IntersectionObserver will set it to false if the
  // element scrolls out of view.
  const [isVisible, setIsVisible] = useState(true)
  const height = heightProp ?? (size === 'compact' ? 192 : 288)

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return

    const observer = new IntersectionObserver(
      ([entry]) => setIsVisible(entry.isIntersecting),
      { threshold: 0 }  // fire as soon as 1px enters viewport
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // If className contains flex-1/h-0/h-full, let CSS control sizing (fillParent mode)
  const useFlexFill = className?.includes('flex-1') || className?.includes('h-full')
  const sentinelStyle = useFlexFill ? undefined : { height }
  const skeletonStyle = useFlexFill ? { height: '100%' } : { height }

  return (
    // sentinel div maintains layout dimensions regardless of whether viewer is mounted
    <div ref={sentinelRef} style={sentinelStyle} className={`w-full${className ? ` ${className}` : ''}`}>
      {isVisible ? (
        <Molecule3DViewer data={data} format={format} size={size} fillParent={useFlexFill} />
      ) : (
        <Skeleton className="w-full h-full rounded-none" style={skeletonStyle} />
      )}
    </div>
  )
}

'use client'

import { useEffect, useRef, useCallback, memo } from 'react'
import { RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'

// 3dmol types – built-in at build/types/index.d.ts
type GLModel = { selectedAtoms: (sel: object) => unknown[] }
type Viewer3D = {
  addModel: (data: string, format: string) => GLModel
  setStyle: (sel: object, style: object) => void
  zoomTo: () => void
  render: () => void
  removeAllModels: () => void
  spin: (axis: string, speed?: number) => void
  stopAnimate: () => void
}

export interface Molecule3DViewerProps {
  data: string
  format: 'sdf' | 'pdbqt'
  /** compact = h-48 (Copilot sidebar), full = h-72 (Agent canvas) */
  size?: 'compact' | 'full'
  /** When true, the viewer stretches to fill its CSS-sized parent (h-full) instead of using a fixed pixel height */
  fillParent?: boolean
}

/** Strip PDBQT-specific columns so 3Dmol can parse it as PDB */
function stripPdbqt(pdbqt: string): string {
  return pdbqt
    .split('\n')
    .map(line =>
      line.startsWith('ATOM') || line.startsWith('HETATM') ? line.slice(0, 66) : line
    )
    .join('\n')
}

/**
 * Ensure a V2000 SDF/MOL block has exactly 3 header lines before the counts
 * line.  Many generators (RDKit, OpenBabel, Marvin) emit the block with a
 * leading blank mol-name line.  If the caller called .trim() on the string the
 * first blank line is lost, shifting the counts line up by one, and 3Dmol
 * silently parses 0 atoms.
 *
 *   Line 1  molecule name  – may be blank
 *   Line 2  program info   – may be blank
 *   Line 3  comment        – may be blank
 *   Line 4  counts         – "aaabbb…V2000"
 */
function normalizeSdf(sdf: string): string {
  const lines = sdf.split('\n')
  // Find the counts line (contains "V2000" or "V3000")
  const countsIdx = lines.findIndex(l => /V2000|V3000/i.test(l))
  if (countsIdx === -1) return sdf          // unknown format – pass through
  if (countsIdx === 3)  return sdf          // already correct

  if (countsIdx < 3) {
    // Too few header lines – prepend blank lines until counts is at index 3
    const missing = 3 - countsIdx
    return '\n'.repeat(missing) + sdf
  }

  // countsIdx > 3: extra leading blank lines – rare but harmless for 3Dmol;
  // leave as-is.
  return sdf
}

// 3Dmol only accepts legacy color formats (#rrggbb, rgb(), named).
// Always use a dark background – Jmol colorscheme H=white would be
// invisible on a white background.
// Slate-900 – dark enough for lab feel, contrast enough for rasmol C=grey
const BG_COLOR = '#0f172a'

function Molecule3DViewerInner({ data, format, size = 'full', fillParent = false }: Molecule3DViewerProps) {
  // containerRef IS the root element – 3Dmol mounts directly on it.
  // Single positioning context: 3Dmol's position:absolute canvas and the
  // toolbar both anchor to the same element, eliminating clip / offset bugs.
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<Viewer3D | null>(null)
  const fixedHeightRef = useRef(size === 'compact' ? 192 : 288)
  const fixedHeight = fixedHeightRef.current

  const resetView = useCallback(() => {
    const v = viewerRef.current
    if (!v) return
    v.zoomTo()
    v.render()
  }, [])

  useEffect(() => {
    if (!containerRef.current || !data) return

    let viewer: Viewer3D | null = null
    let cancelled = false
    let rafId1: number
    let rafId2: number

    const init = async () => {
      const $3Dmol = await import('3dmol')
      if (cancelled || !containerRef.current) return

      // Double RAF: wait for the browser to finish layout/paint before reading
      // dimensions. next/dynamic chunks arrive before the DOM is fully sized.
      await new Promise<void>(resolve => {
        rafId1 = requestAnimationFrame(() => {
          rafId2 = requestAnimationFrame(() => resolve())
        })
      })
      if (cancelled || !containerRef.current) return

      const el = containerRef.current
      const rect = el.getBoundingClientRect()
      const w = Math.round(rect.width)  || 400
      const h = Math.round(rect.height) || fixedHeight

      viewer = ($3Dmol as unknown as {
        createViewer: (el: HTMLElement, opts: object) => Viewer3D
      }).createViewer(el, {
        backgroundColor: BG_COLOR,
        width: w,
        height: h,
        antialias: false,   // patch-2: disables MSAA → frees GPU on every frame
        nomouse: false,
      })

      viewerRef.current = viewer

      try {
        const loadFormat = format === 'pdbqt' ? 'pdb' : format
        const rawData    = format === 'pdbqt' ? stripPdbqt(data) : data
        const loadData   = loadFormat === 'sdf' ? normalizeSdf(rawData) : rawData
        const model = viewer.addModel(loadData, loadFormat)
        const atomCount = model?.selectedAtoms({}).length ?? '?'
        console.log('[Mol3D] atom count:', atomCount)
        viewer.setStyle({}, {
          stick:  { radius: 0.15, colorscheme: 'rasmol', quality: 'low' },
          sphere: { scale: 0.3,  colorscheme: 'rasmol', quality: 'low' },
        })
        viewer.zoomTo()
        viewer.render()
        console.log('[Mol3D] render() done')
      } catch (err) {
        console.error('[Molecule3DViewer] render error:', err)
      }
    }

    init()

    return () => {
      cancelled = true
      cancelAnimationFrame(rafId1)
      cancelAnimationFrame(rafId2)
      if (viewer) {
        try { viewer.removeAllModels() } catch (_) { /* ignore */ }
      }
      viewerRef.current = null
    }
  }, [data, format, fillParent])

  return (
    /*
     * containerRef = root element. 3Dmol creates a position:absolute canvas
     * inside and positions it relative to the nearest positioned ancestor —
     * that IS this div. Toolbar also lives here → same coordinate system.
     * overflow:hidden is intentionally absent: it clips 3Dmol's canvas edges
     * and breaks its pointer-event handlers.
     */
    <div
      ref={containerRef}
      style={fillParent
        ? { position: 'relative', height: '100%', background: BG_COLOR }
        : { position: 'relative', height: fixedHeight, background: BG_COLOR }
      }
      className="w-full"
      aria-label={`3D molecular viewer – ${format.toUpperCase()}`}
    >
      {/* Floating toolbar */}
      <div className="absolute top-1.5 right-1.5 flex items-center gap-1 z-10 pointer-events-none">
        <span className="pointer-events-auto text-[10px] text-white/60 bg-black/40 backdrop-blur-sm px-1.5 py-0.5 rounded-sm select-none">
          {format.toUpperCase()} · 3D
        </span>
        <Button
          size="icon"
          variant="ghost"
          className="pointer-events-auto h-6 w-6 text-white/60 hover:text-white bg-black/40 backdrop-blur-sm hover:bg-black/60"
          onClick={resetView}
          title="重置视角"
          aria-label="重置视角"
        >
          <RotateCcw className="h-3 w-3" />
        </Button>
      </div>

      {/* Interaction hint */}
      <div className="absolute bottom-1 left-0 right-0 flex justify-center pointer-events-none">
        <span className="text-[9px] text-white/40 bg-black/30 backdrop-blur-sm px-1.5 py-0.5 rounded-sm">
          拖拽旋转 · 滚轮缩放
        </span>
      </div>
    </div>
  )
}

/**
 * Patch-1: memo + custom comparator.
 * The SSE stream updates sseStore/uiStore tens of times per second while the
 * agent is running.  Without memo, every parent re-render would unmount and
 * remount the WebGL canvas, causing visible flash and draining the main thread.
 * We only re-render when the molecule data, format or viewport size truly changes.
 */
export const Molecule3DViewer = memo(Molecule3DViewerInner, (prev, next) =>
  prev.data       === next.data       &&
  prev.format     === next.format     &&
  prev.size       === next.size       &&
  prev.fillParent === next.fillParent
)

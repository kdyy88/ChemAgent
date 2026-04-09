'use client'

import { useCallback, useRef, useState } from 'react'
import { AgentChatPanel } from './AgentChatPanel'
import { ArtifactCanvas } from './ArtifactCanvas'

const MIN_LEFT_PX = 280
const MAX_LEFT_RATIO = 0.65

/**
 * AgentLayout — Gemini-Canvas style split layout for autonomous Agent mode.
 *
 * Left  — AgentChatPanel  (resizable, min 280px, max 65%)
 * Right — ArtifactCanvas  (flex-1, takes remaining space)
 *
 * Uses native pointer-event drag instead of react-resizable-panels to avoid
 * the container-width-collapse bug that limits dragging range.
 */
export function AgentLayout() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [leftWidth, setLeftWidth] = useState<number>(360)
  const dragging = useRef(false)

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    dragging.current = true
  }, [])

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current || !containerRef.current) return
    const containerLeft = containerRef.current.getBoundingClientRect().left
    const containerWidth = containerRef.current.offsetWidth
    const desired = e.clientX - containerLeft
    const maxLeft = Math.floor(containerWidth * MAX_LEFT_RATIO)
    setLeftWidth(Math.max(MIN_LEFT_PX, Math.min(maxLeft, desired)))
  }, [])

  const onPointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.currentTarget.releasePointerCapture(e.pointerId)
    dragging.current = false
  }, [])

  return (
    <div ref={containerRef} className="flex h-full w-full overflow-hidden">
      {/* ── Left: Chat panel ── */}
      <div
        className="flex-none h-full overflow-hidden"
        style={{ width: leftWidth }}
      >
        <AgentChatPanel />
      </div>

      {/* ── Drag handle ── */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panels"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        className="
          relative z-10 flex-none w-1 cursor-col-resize
          bg-border/50 hover:bg-primary/50 active:bg-primary
          transition-colors duration-150
          after:absolute after:inset-y-0 after:-left-1.5 after:-right-1.5
        "
      >
        {/* Visual pill */}
        <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 flex items-center justify-center">
          <div className="h-8 w-1 rounded-full bg-border group-hover:bg-primary/70" />
        </div>
      </div>

      {/* ── Right: Artifact canvas ── */}
      <div className="flex-1 h-full min-w-0 overflow-hidden">
        <ArtifactCanvas />
      </div>
    </div>
  )
}

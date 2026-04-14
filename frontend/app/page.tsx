'use client'

import { useCallback, useRef, useState, useSyncExternalStore } from 'react'
import Link from 'next/link'
import { PlusCircle, FlaskConical, ScrollText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useSseStore } from '@/store/sseStore'
import { useUIStore } from '@/store/uiStore'
import { useMediaQuery } from '@/hooks/use-media-query'
import { ToolSidebar } from '@/components/workspace/ToolSidebar'
import { WorkspaceArea } from '@/components/workspace/WorkspaceArea'
import { CopilotSidebar } from '@/components/chat/CopilotSidebar'
import { AgentLayout } from '@/components/agent/AgentLayout'
import GlobalLoading from './loading'
import { ThemeToggle } from '@/components/ui/ThemeToggle'
import { LanguageSwitcher } from '@/components/ui/LanguageSwitcher'

const MIN_COPILOT_RATIO = 20
const MAX_COPILOT_RATIO = 60
const DEFAULT_COPILOT_RATIO = 20

function useHasMounted() {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  )
}

export default function Home() {
  const clearTurns = useSseStore((s) => s.clearTurns)
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const isMounted = useHasMounted()
  const { appMode, isSidebarExpanded } = useUIStore()
  const contentRef = useRef<HTMLDivElement>(null)
  const [copilotWidthPct, setCopilotWidthPct] = useState(DEFAULT_COPILOT_RATIO)
  const dragging = useRef(false)

  const onResizeStart = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    dragging.current = true
  }, [])

  const onResizeMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current || !contentRef.current) return
    const rect = contentRef.current.getBoundingClientRect()
    if (rect.width <= 0) return

    const desired = ((rect.right - e.clientX) / rect.width) * 100
    const next = Math.max(MIN_COPILOT_RATIO, Math.min(MAX_COPILOT_RATIO, desired))
    setCopilotWidthPct(next)
  }, [])

  const onResizeEnd = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
    dragging.current = false
  }, [])

  if (!isMounted) {
    return <GlobalLoading />
  }

  return (
    <main className="flex flex-col h-[100dvh] bg-background">
      {/* ── Application Header ── */}
      <header className="shrink-0 border-b border-border/70 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 z-10 relative">
        <div className="w-full px-4 md:px-5 h-12 flex items-center gap-3">
          {/* Brand */}
          <div className="flex items-center gap-2.5 shrink-0">
            <div className="relative flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 border border-primary/20" aria-hidden="true">
              <FlaskConical className="h-3.5 w-3.5 text-primary" />
            </div>
            <div className="leading-none">
              <h1 className="font-display text-[13px] font-700 tracking-[-0.03em] text-foreground">
                Chem<span className="text-primary">Agent</span>
              </h1>
            </div>
          </div>

          {/* Separator */}
          <div className="h-5 w-px bg-border/60 hidden sm:block" aria-hidden="true" />

          {/* Nav label */}
          <span className="hidden sm:block text-[11px] text-muted-foreground/60 tracking-[0.06em] uppercase font-medium select-none">
            AI Chemistry Platform
          </span>

          <div className="flex-1" />

          {/* Actions */}
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={clearTurns}
              className="h-7 gap-1.5 px-2.5 text-[12px] text-muted-foreground hover:text-foreground hover:bg-muted/60 font-medium"
              aria-label="新建对话"
            >
              <PlusCircle className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">New Chat</span>
            </Button>
            <Link
              href="/changelog"
              className="flex items-center gap-1.5 rounded-md h-7 px-2.5 text-[12px] text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors font-medium"
              aria-label="更新日志"
            >
              <ScrollText className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="hidden md:inline">Changelog</span>
            </Link>
            <div className="h-5 w-px bg-border/60 mx-0.5" aria-hidden="true" />
            <LanguageSwitcher />
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* ── Main content: mode-driven layout ── */}
      <div className="flex-1 overflow-hidden relative">
        {appMode === 'agent' ? (
          <div className="h-full w-full overflow-hidden relative bg-background">
            <AgentLayout />
          </div>
        ) : (
          <div className="flex h-full w-full">
            {/* Nav Sidebar (fixed width, collapsible) */}
            <div 
              className={`shrink-0 h-full bg-background border-r border-border/50 flex flex-col transition-[width] duration-300 ease-in-out ${
                isSidebarExpanded ? 'w-[240px] md:w-[260px]' : 'w-[46px]'
              }`}
            >
              <ToolSidebar />
            </div>

            {/* Resizable Area for Workspace and Chat */}
            <div ref={contentRef} className="flex-1 h-full min-w-0 bg-background">
              {isDesktop ? (
                <div className="flex h-full w-full overflow-hidden">
                  <div className="min-w-0 flex-1 bg-background relative z-10 z-index-[1] overflow-hidden">
                    <div className="h-full w-full mx-auto max-w-5xl">
                      <WorkspaceArea />
                    </div>
                  </div>

                  <div
                    role="separator"
                    aria-orientation="vertical"
                    aria-label="Resize panels"
                    onPointerDown={onResizeStart}
                    onPointerMove={onResizeMove}
                    onPointerUp={onResizeEnd}
                    className="relative z-10 flex-none w-1 md:w-1.5 cursor-col-resize bg-border/20 hover:bg-primary/20 active:bg-primary/40 transition-colors"
                  />

                  <div
                    className="h-full shrink-0 bg-muted/10 border-l border-border/50 overflow-hidden relative"
                    style={{ width: `${copilotWidthPct}%` }}
                  >
                    <CopilotSidebar />
                  </div>
                </div>
              ) : (
                <div className="flex h-full w-full flex-col overflow-hidden">
                  <div className="min-h-0 flex-1 bg-background relative z-10 z-index-[1] overflow-hidden">
                    <div className="h-full w-full mx-auto max-w-5xl">
                      <WorkspaceArea />
                    </div>
                  </div>
                  <div className="h-px bg-border/20" aria-hidden="true" />
                  <div className="min-h-[36dvh] bg-muted/10 border-t border-border/50 overflow-hidden relative">
                    <CopilotSidebar />
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <footer className="shrink-0 border-t border-border/50 bg-background py-1 z-10 relative">
        <p className="text-center text-[10px] text-muted-foreground/60 select-none tracking-wide font-medium">
          © {new Date().getFullYear()} ChemAgent · Yuan Ye &amp; Kelly
        </p>
      </footer>
    </main>
  )
}

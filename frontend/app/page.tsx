'use client'

import { useSyncExternalStore } from 'react'
import Link from 'next/link'
import { PlusCircle, FlaskConical, ScrollText, TestTubeDiagonal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useSseStore } from '@/store/sseStore'
import { useUIStore } from '@/store/uiStore'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { useMediaQuery } from '@/hooks/use-media-query'
import { ToolSidebar } from '@/components/workspace/ToolSidebar'
import { WorkspaceArea } from '@/components/workspace/WorkspaceArea'
import { CopilotSidebar } from '@/components/chat/CopilotSidebar'
import { AgentLayout } from '@/components/agent/AgentLayout'
import GlobalLoading from './loading'
import { ThemeToggle } from '@/components/ui/ThemeToggle'
import { LanguageSwitcher } from '@/components/ui/LanguageSwitcher'

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
  const { appMode } = useUIStore()

  if (!isMounted) {
    return <GlobalLoading />
  }

  return (
    <main className="flex flex-col h-[100dvh] bg-background">
      <header className="shrink-0 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="w-full px-4 md:px-6 py-3 flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary ring-2 ring-primary/20" aria-hidden="true">
            <FlaskConical className="h-4 w-4 text-primary-foreground" />
          </div>
          <div className="flex-1">
            <h1 className="font-display text-sm font-bold leading-none tracking-wide">
              Chem<span className="text-primary">Agent</span>
            </h1>
            <p className="text-[10px] text-muted-foreground mt-0.5 font-mono tracking-widest uppercase">AI Chemistry Expert</p>
          </div>

          <Button
            variant="ghost"
            size="sm"
            onClick={clearTurns}
            className="gap-1.5 text-muted-foreground hover:text-foreground"
            aria-label="新建对话"
          >
            <PlusCircle className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline text-xs">New Chat</span>
          </Button>
          <Link
            href="/changelog"
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
            aria-label="更新日志"
          >
            <ScrollText className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">更新日志</span>
          </Link>
          <Link
            href="/mvp"
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
            aria-label="MVP 测试页面"
          >
            <TestTubeDiagonal className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">MVP Test</span>
          </Link>
          <LanguageSwitcher />
          <ThemeToggle />
        </div>
      </header>

      {/* ── Main content: mode-driven layout ── */}
      <div className="flex-1 overflow-hidden">
        {appMode === 'agent' ? (
          <AgentLayout />
        ) : (
          <ResizablePanelGroup orientation={isDesktop ? 'horizontal' : 'vertical'}>
            <ResizablePanel defaultSize={15} minSize="12%">
              <ToolSidebar />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize={60} minSize="30%">
              <div className="h-full w-full mx-auto max-w-4xl ">
                <WorkspaceArea />
              </div>
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize={15} minSize="12%">
              <CopilotSidebar />
            </ResizablePanel>
          </ResizablePanelGroup>
        )}
      </div>

      {/* Footer */}
      <footer className="shrink-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-t pt-1 pb-1">
        <p className="text-center text-[10px] text-muted-foreground/70 select-none">
          © {new Date().getFullYear()} ChemAgent · Designed &amp; developed by Yuan Ye · Consulting by Kelly 
        </p>
      </footer>
    </main>
  )
}

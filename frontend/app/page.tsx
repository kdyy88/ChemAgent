'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { PlusCircle, FlaskConical, LayoutTemplate } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { TeamSettingsPopover } from '@/components/chat/TeamSettingsPopover'
import { ConnectionStatusBadge } from '@/components/chat/ConnectionStatusBadge'
import { useChemAgent } from '@/hooks/useChemAgent'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { useMediaQuery } from '@/hooks/use-media-query'
import { ToolSidebar } from '@/components/workspace/ToolSidebar'
import { WorkspaceArea } from '@/components/workspace/WorkspaceArea'
import { CopilotSidebar } from '@/components/chat/CopilotSidebar'
import GlobalLoading from './loading'

export default function Home() {
  const { clearTurns, connectionStatus } = useChemAgent()
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const [isMounted, setIsMounted] = useState(false)

  useEffect(() => {
    setIsMounted(true)
  }, [])

  if (!isMounted) {
    return <GlobalLoading />
  }

  return (
    <main className="flex flex-col h-[100dvh] bg-background">
      <header className="shrink-0 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="w-full px-4 md:px-6 py-3 flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <FlaskConical className="h-4 w-4 text-primary-foreground" />
          </div>
          <div className="flex-1">
            <h1 className="text-sm font-semibold leading-none">ChemAgent</h1>
            <p className="text-xs text-muted-foreground mt-0.5">AI Chemistry Expert</p>
          </div>

          <ConnectionStatusBadge status={connectionStatus} />

          <Button
            variant="ghost"
            size="sm"
            onClick={clearTurns}
            className="gap-1.5 text-muted-foreground hover:text-foreground"
          >
            <PlusCircle className="h-4 w-4" />
            <span className="hidden sm:inline text-xs">New Chat</span>
          </Button>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-foreground" asChild>
                <Link href="/workflow">
                  <LayoutTemplate className="h-4 w-4" />
                </Link>
              </Button>
            </TooltipTrigger>
            <TooltipContent>Workflow Editor</TooltipContent>
          </Tooltip>
          <TeamSettingsPopover />
        </div>
      </header>

      {/* Main Content Resizable Split */}
      <div className="flex-1 overflow-hidden">
        <ResizablePanelGroup orientation={isDesktop ? 'horizontal' : 'vertical'}>
          <ResizablePanel defaultSize={15} minSize={10}>
            <ToolSidebar />
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={60} minSize={40} className="bg-zinc-50/50 dark:bg-zinc-950/50">
            <div className="h-full w-full mx-auto max-w-4xl ">
              <WorkspaceArea />
            </div>
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={15} minSize={10}>
            <CopilotSidebar />
          </ResizablePanel>
        </ResizablePanelGroup>
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

'use client'

import { PlusCircle } from 'lucide-react'
import { FlaskConical } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { MessageList } from '@/components/chat/MessageList'
import { ChatInput } from '@/components/chat/ChatInput'
import { TeamSettingsPopover } from '@/components/chat/TeamSettingsPopover'
import { SmilesPanelSheet } from '@/components/chat/SmilesPanelSheet'
import { useChemAgent } from '@/hooks/useChemAgent'

export default function Home() {
  const { clearTurns } = useChemAgent()

  return (
    <main className="flex flex-col h-[100dvh] bg-background">
      {/* Header */}
      <header className="shrink-0 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <FlaskConical className="h-4 w-4 text-primary-foreground" />
          </div>
          <div className="flex-1">
            <h1 className="text-sm font-semibold leading-none">ChemAgent</h1>
            <p className="text-xs text-muted-foreground mt-0.5">AI Chemistry Expert</p>
          </div>

          {/* Header actions */}
          <Button
            variant="ghost"
            size="sm"
            onClick={clearTurns}
            className="gap-1.5 text-muted-foreground hover:text-foreground"
          >
            <PlusCircle className="h-4 w-4" />
            <span className="hidden sm:inline text-xs">New Chat</span>
          </Button>
          <SmilesPanelSheet />
          <TeamSettingsPopover />
        </div>
      </header>

      {/* Chat area */}
      <div className="flex-1 overflow-hidden">
        <MessageList />
      </div>

      {/* Input bar */}
      <footer className="shrink-0 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="max-w-5xl mx-auto px-4 py-3">
          <ChatInput />
        </div>
        <p className="text-center text-[10px] text-muted-foreground/70 pb-2 select-none">
          © {new Date().getFullYear()} ChemAgent · Designed &amp; developed by Yuan Ye · Consulting by Kelly 
        </p>
      </footer>
    </main>
  )
}

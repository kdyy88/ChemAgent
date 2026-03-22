'use client'

import { MessageList } from './MessageList'
import { ChatInput } from './ChatInput'

export function CopilotSidebar() {
  return (
    <div className="flex flex-col h-full bg-muted/10 border-l relative shadow-inner">
      <div className="flex-1 overflow-hidden">
        <MessageList />
      </div>
      <div className="shrink-0 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 p-4">
        <ChatInput />
      </div>
    </div>
  )
}

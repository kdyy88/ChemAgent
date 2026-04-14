'use client'

import { FlaskConical } from 'lucide-react'
import {
  ChatContainerRoot,
  ChatContainerContent,
  ChatContainerScrollAnchor,
} from '@/components/ui/chat-container'
import { ScrollButton } from '@/components/ui/scroll-button'
import { SSEMessageBubble } from './SSEMessageBubble'
import type { SSETurn } from '@/lib/sse-types'

interface SSEMessageListProps {
  turns: SSETurn[]
}

export function SSEMessageList({ turns }: SSEMessageListProps) {
  return (
    <div className="relative h-full">
      <ChatContainerRoot className="h-full">
        <ChatContainerContent className="max-w-5xl mx-auto w-full px-4 py-6 gap-6">
          {turns.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-border/50 bg-muted/30">
                <FlaskConical className="h-5 w-5 text-muted-foreground/50" />
              </div>
              <div className="space-y-1">
                <p className="text-[13px] font-medium text-foreground/70">
                  Ask me about any chemical compound
                </p>
                <p className="text-[12px] text-muted-foreground/50">
                  Try &ldquo;Aspirin&rdquo; or &ldquo;CC(=O)Oc1ccccc1C(=O)O&rdquo;
                </p>
              </div>
            </div>
          ) : (
            turns.map((turn) => (
              <SSEMessageBubble key={turn.turnId} turn={turn} />
            ))
          )}
          <ChatContainerScrollAnchor />
        </ChatContainerContent>
        <div className="absolute right-4 bottom-4 z-10">
          <ScrollButton />
        </div>
      </ChatContainerRoot>
    </div>
  )
}

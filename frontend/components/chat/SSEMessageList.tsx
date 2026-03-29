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
            <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted">
                <FlaskConical className="h-8 w-8 text-muted-foreground" />
              </div>
              <div className="space-y-1">
                <p className="text-base font-medium text-foreground">
                  Ask me about any chemical compound
                </p>
                <p className="text-sm text-muted-foreground">
                  Try entering a name like &ldquo;Aspirin&rdquo; or &ldquo;扑热息痛&rdquo;
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

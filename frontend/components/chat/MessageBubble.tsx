'use client'

import { memo } from 'react'
import { FlaskConical } from 'lucide-react'
import { Message, MessageContent } from '@/components/ui/message'
import { Loader } from '@/components/ui/loader'
import { Skeleton } from '@/components/ui/skeleton'
import { ThinkingLog } from './ThinkingLog'
import { ArtifactGallery } from './ArtifactGallery'
import type { ToolMeta, Turn } from '@/lib/types'

interface MessageBubbleProps {
  turn: Turn
  toolCatalog: Record<string, ToolMeta>
}

export const MessageBubble = memo(function MessageBubble({ turn, toolCatalog }: MessageBubbleProps) {
  // Prefer the dedicated finalAnswer (Manager synthesis) when available;
  // fall back only for legacy sessions whose agent replies had no sender.
  const displayContent =
    turn.finalAnswer ??
    ([...turn.steps].reverse().find((s) => s.kind === 'agent_reply' && !s.sender) as
      | { kind: 'agent_reply'; content: string }
      | undefined)?.content

  const isThinking = turn.status === 'thinking'
  const showSkeleton = isThinking && !displayContent

  return (
    <div className="flex flex-col gap-3">
      {/* User bubble — right-aligned; hidden for auto-generated greeting turns */}
      {!turn.isGreeting && (
        <div className="flex justify-end">
          <Message className="max-w-[75%]">
            <MessageContent className="rounded-2xl bg-primary text-primary-foreground px-4 py-2.5 text-sm leading-relaxed shadow-sm">
              {turn.userMessage}
            </MessageContent>
          </Message>
        </div>
      )}

      {/* Agent response — left-aligned */}
      <Message className="items-start gap-2.5">
        {/* Avatar */}
        <div className="shrink-0 mt-0.5 flex h-7 w-7 items-center justify-center rounded-full bg-muted border">
          <FlaskConical className="h-3.5 w-3.5 text-muted-foreground" />
        </div>

        {/* Content column */}
        <div className="flex flex-col gap-1.5 min-w-0 flex-1">
          <span className="text-xs font-medium text-muted-foreground">ChemAgent</span>

          <ThinkingLog
            steps={turn.steps}
            status={turn.status}
            startedAt={turn.startedAt}
            finishedAt={turn.finishedAt}
            toolCatalog={toolCatalog}
            statusMessage={turn.statusMessage}
          />

          {showSkeleton ? (
            <div className="rounded-2xl border bg-card px-4 py-3 shadow-sm space-y-2">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-5/6" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          ) : displayContent ? (
            isThinking ? (
              // During streaming: plain text prevents Markdown from
              // re-parsing the AST on every token (which causes layout jumps).
              <div className="rounded-2xl border bg-card px-4 py-3 text-sm leading-relaxed shadow-sm flex items-center gap-2 flex-wrap">
                <span className="whitespace-pre-wrap">{displayContent}</span>
                <Loader variant="typing" size="sm" className="shrink-0" />
              </div>
            ) : (
              // Streaming complete: render full Markdown once.
              <MessageContent
                markdown
                className="rounded-2xl border bg-card px-4 py-3 text-sm leading-relaxed shadow-sm prose prose-sm dark:prose-invert max-w-none"
              >
                {displayContent}
              </MessageContent>
            )
          ) : null}

          {!isThinking && <ArtifactGallery artifacts={turn.artifacts} />}
        </div>
      </Message>
    </div>
  )
})


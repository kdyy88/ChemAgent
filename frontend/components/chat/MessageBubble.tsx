'use client'

import { memo } from 'react'
import { FlaskConical } from 'lucide-react'
import { Message, MessageContent } from '@/components/ui/message'
import { Loader } from '@/components/ui/loader'
import { Skeleton } from '@/components/ui/skeleton'
import { ThinkingLog } from './ThinkingLog'
import { ArtifactGallery } from './ArtifactGallery'
import { StreamingText } from './StreamingText'
import type { Turn } from '@/lib/types'

interface MessageBubbleProps {
  turn: Turn
}

/**
 * Strip structural XML blocks (<plan>, <todo>) from live-streaming tokens.
 * This ensures raw markup never appears in the answer bubble even while
 * tokens are still arriving.
 *
 * Strategy:
 * 1. Remove fully-closed blocks (clean case)
 * 2. Remove from any still-open structural tag to end-of-string
 *    (handles mid-stream partial blocks where </plan> hasn't arrived yet)
 */
function stripLiveStructural(text: string): string {
  let r = text.replace(/<plan>[\s\S]*?<\/plan>/g, '')
  r = r.replace(/<todo>[\s\S]*?<\/todo>/g, '')
  // Remove from unclosed opening tag to end of string
  r = r.replace(/<(plan|todo)[^>]*>[\s\S]*$/, '')
  r = r.replace(/\[AWAITING_APPROVAL\]|\[TERMINATE\]/g, '')
  return r.trimStart()
}

export const MessageBubble = memo(function MessageBubble({ turn }: MessageBubbleProps) {
  const isThinking = turn.status === 'thinking' || turn.status === 'awaiting_approval'

  // draftAnswer: raw token stream for the CURRENT LLM turn (may contain XML markup)
  // finalAnswer: clean committed text from completed LLM turns
  const liveDraft = turn.draftAnswer ? stripLiveStructural(turn.draftAnswer) : undefined

  // Combined live view: committed text + current streaming tokens (filtered)
  const liveContent = [turn.finalAnswer, liveDraft].filter(Boolean).join('\n\n')

  // Skeleton only when thinking but nothing has arrived yet
  const showSkeleton = isThinking && !liveContent

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
            statusMessage={turn.statusMessage}
          />

          {showSkeleton ? (
            <div className="rounded-2xl border bg-card px-4 py-3 shadow-sm space-y-2">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-5/6" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          ) : liveContent && isThinking ? (
            // Live streaming view: committed text + current tokens, with loader
            <div className="rounded-2xl border bg-card px-4 py-3 text-sm leading-relaxed shadow-sm">
              <StreamingText text={liveContent} />
              <Loader variant="typing" size="sm" className="mt-2" />
            </div>
          ) : turn.finalAnswer ? (
            // Streaming complete: render full Markdown once.
            <MessageContent
              markdown
              className="rounded-2xl border bg-card px-4 py-3 text-sm leading-relaxed shadow-sm prose prose-sm dark:prose-invert max-w-none"
            >
              {turn.finalAnswer}
            </MessageContent>
          ) : null}

          {!isThinking && <ArtifactGallery artifacts={turn.artifacts} />}
        </div>
      </Message>
    </div>
  )
})


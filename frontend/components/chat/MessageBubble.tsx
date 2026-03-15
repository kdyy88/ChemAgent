'use client'

import { memo } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { FlaskConical } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ThinkingLog } from './ThinkingLog'
import { ArtifactGallery } from './ArtifactGallery'
import { Skeleton } from '@/components/ui/skeleton'
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
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="flex flex-col gap-3"
    >
      {/* User bubble — right-aligned; hidden for auto-generated greeting turns */}
      {!turn.isGreeting && (
        <div className="flex justify-end">
          <div className="max-w-[75%] rounded-2xl bg-primary text-primary-foreground px-4 py-2.5 text-sm leading-relaxed shadow-sm">
            {turn.userMessage}
          </div>
        </div>
      )}

      {/* Agent response — left-aligned */}
      <div className="flex items-start gap-2.5">
        {/* Avatar */}
        <div className="shrink-0 mt-0.5 flex h-7 w-7 items-center justify-center rounded-full bg-muted border">
          <FlaskConical className="h-3.5 w-3.5 text-muted-foreground" />
        </div>

        {/* Content */}
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

          <AnimatePresence mode="wait">
            {showSkeleton ? (
              <motion.div
                key="skeleton"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="rounded-2xl border bg-card px-4 py-3 shadow-sm space-y-2"
              >
                <Skeleton className="h-3 w-3/4" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-5/6" />
                <Skeleton className="h-3 w-2/3" />
              </motion.div>
            ) : displayContent ? (
              <motion.div
                key="answer"
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, ease: 'easeOut' }}
                className="rounded-2xl border bg-card px-4 py-3 text-sm leading-relaxed shadow-sm"
              >
                {isThinking ? (
                  // During streaming: plain text prevents ReactMarkdown from
                  // re-parsing the AST on every token (which causes layout jumps).
                  <span className="whitespace-pre-wrap">
                    {displayContent}
                    <span className="inline-block w-[2px] h-[1em] ml-[1px] align-text-bottom bg-foreground/70 animate-pulse" />
                  </span>
                ) : (
                  // Streaming complete: render full Markdown once.
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {displayContent}
                    </ReactMarkdown>
                  </div>
                )}
              </motion.div>
            ) : null}
          </AnimatePresence>

          {!isThinking && <ArtifactGallery artifacts={turn.artifacts} />}
        </div>
      </div>
    </motion.div>
  )
})


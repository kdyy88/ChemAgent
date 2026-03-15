'use client'

import { motion } from 'framer-motion'
import { FlaskConical } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ThinkingLog } from './ThinkingLog'
import { ArtifactGallery } from './ArtifactGallery'
import type { ToolMeta, Turn } from '@/lib/types'

interface MessageBubbleProps {
  turn: Turn
  toolCatalog: Record<string, ToolMeta>
}

export function MessageBubble({ turn, toolCatalog }: MessageBubbleProps) {
  // Prefer the dedicated finalAnswer (Manager synthesis) when available;
  // fall back only for legacy sessions whose agent replies had no sender.
  const displayContent =
    turn.finalAnswer ??
    ([...turn.steps].reverse().find((s) => s.kind === 'agent_reply' && !s.sender) as
      | { kind: 'agent_reply'; content: string }
      | undefined)?.content

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="flex flex-col gap-3"
    >
      {/* User bubble — right-aligned */}
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl bg-primary text-primary-foreground px-4 py-2.5 text-sm leading-relaxed shadow-sm">
          {turn.userMessage}
        </div>
      </div>

      {/* Agent response — left-aligned */}
      <div className="flex items-start gap-2.5">
        {/* Avatar */}
        <div className="shrink-0 mt-0.5 flex h-7 w-7 items-center justify-center rounded-full bg-muted border">
          <FlaskConical className="h-3.5 w-3.5 text-muted-foreground" />
        </div>

        {/* Content */}
        <div className="flex flex-col gap-1.5 min-w-0">
          <span className="text-xs font-medium text-muted-foreground">ChemAgent</span>

          <ThinkingLog
            steps={turn.steps}
            status={turn.status}
            startedAt={turn.startedAt}
            finishedAt={turn.finishedAt}
            toolCatalog={toolCatalog}
          />

          {displayContent && (
            <div className="rounded-2xl border bg-card px-4 py-3 text-sm leading-relaxed shadow-sm prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {displayContent}
              </ReactMarkdown>
            </div>
          )}

          <ArtifactGallery artifacts={turn.artifacts} />
        </div>
      </div>
    </motion.div>
  )
}

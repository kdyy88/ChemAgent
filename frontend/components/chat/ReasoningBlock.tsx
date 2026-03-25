'use client'

import { memo, useState } from 'react'
import { Brain, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ReasoningBlockProps {
  content: string
  /** Whether the model is still streaming reasoning tokens */
  isStreaming?: boolean
}

/**
 * Collapsible panel displaying the model's internal reasoning / chain-of-thought.
 *
 * - Collapsed by default (reasoning can be verbose)
 * - Muted gray styling to visually differentiate from tool calls
 * - Italic text with subtle background
 */
export const ReasoningBlock = memo(function ReasoningBlock({
  content,
  isStreaming = false,
}: ReasoningBlockProps) {
  const [open, setOpen] = useState(false)

  if (!content) return null

  const preview = content.slice(0, 60).replace(/\n/g, ' ')
  const truncated = content.length > 60

  return (
    <div className="rounded-md border border-muted/50 bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          'flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-xs',
          'text-muted-foreground hover:text-foreground/80 transition-colors',
        )}
      >
        <Brain className={cn('h-3.5 w-3.5 shrink-0', isStreaming && 'animate-pulse text-violet-400')} />
        <span className="font-medium">思维过程</span>
        {isStreaming && (
          <span className="ml-1 inline-flex gap-0.5 text-violet-400">
            <span className="animate-bounce [animation-delay:0ms]">.</span>
            <span className="animate-bounce [animation-delay:150ms]">.</span>
            <span className="animate-bounce [animation-delay:300ms]">.</span>
          </span>
        )}
        {!open && (
          <span className="ml-auto truncate text-[10px] italic opacity-50 max-w-[200px]">
            {preview}{truncated ? '…' : ''}
          </span>
        )}
        <ChevronRight
          className={cn(
            'h-3 w-3 shrink-0 transition-transform ml-auto',
            open && 'rotate-90',
          )}
        />
      </button>
      {open && (
        <div className="border-t border-muted/50 px-2.5 py-2 max-h-60 overflow-y-auto">
          <p className="text-[11px] leading-relaxed italic text-muted-foreground whitespace-pre-wrap break-words font-mono">
            {content}
          </p>
        </div>
      )}
    </div>
  )
})

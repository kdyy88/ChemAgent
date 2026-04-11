'use client'

import { useEffect, useRef } from 'react'
import { Workflow } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

interface PlanDraftStreamProps {
  text: string
  isStreaming: boolean
}

export function PlanDraftStream({ text, isStreaming }: PlanDraftStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom as tokens stream in
  useEffect(() => {
    if (isStreaming) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [text, isStreaming])

  if (!text) return null

  return (
    <div className="flex flex-col gap-0 rounded-3xl border border-amber-300/70 bg-[linear-gradient(180deg,rgba(255,251,235,0.96),rgba(255,247,214,0.82))] shadow-sm dark:border-amber-800/50 dark:bg-[linear-gradient(180deg,rgba(56,38,7,0.32),rgba(33,21,4,0.6))] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-amber-200/70 px-4 py-2.5 dark:border-amber-800/40">
        <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-600 dark:bg-amber-950/60 dark:text-amber-400">
          <Workflow className="h-3.5 w-3.5" />
        </div>
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-700 dark:text-amber-400">
          Planning · 规划中
        </span>
        {isStreaming && (
          <span className="ml-auto flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="block h-1 w-1 rounded-full bg-amber-500 dark:bg-amber-400"
                style={{
                  animation: 'bounce 1.2s ease-in-out infinite',
                  animationDelay: `${i * 0.2}s`,
                }}
              />
            ))}
          </span>
        )}
      </div>

      {/* Streaming Markdown content */}
      <div className="max-h-[420px] overflow-y-auto px-4 py-3.5">
        <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:font-semibold prose-headings:text-amber-900 dark:prose-headings:text-amber-200 prose-strong:text-amber-800 dark:prose-strong:text-amber-300 prose-code:text-[11px] prose-pre:bg-amber-50/80 dark:prose-pre:bg-amber-950/40 prose-li:my-0.5 prose-p:my-1">
          <ReactMarkdown>{text}</ReactMarkdown>
        </div>
        <div ref={bottomRef} className="h-px" />
      </div>
    </div>
  )
}

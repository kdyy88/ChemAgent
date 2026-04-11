'use client'

import { useEffect, useRef } from 'react'
import { Workflow } from 'lucide-react'
import { parsePlanPreview } from '@/lib/plan-preview'

interface PlanDraftStreamProps {
  text: string
  isStreaming: boolean
}

export function PlanDraftStream({ text, isStreaming }: PlanDraftStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const preview = parsePlanPreview(text)

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

      {/* Streaming summary content */}
      <div className="max-h-[420px] overflow-y-auto px-4 py-3.5">
        <div className="flex flex-col gap-3">
          {preview.goal && (
            <div className="rounded-2xl border border-amber-200/70 bg-amber-50/70 px-3 py-2 dark:border-amber-800/40 dark:bg-amber-950/20">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-700 dark:text-amber-300">
                总体目标
              </p>
              <p className="mt-1 text-sm leading-relaxed text-foreground/85">{preview.goal}</p>
            </div>
          )}

          {preview.stages.length > 0 ? (
            <div className="flex flex-col gap-2.5">
              {preview.stages.map((stage, index) => (
                <section
                  key={stage.id}
                  className="rounded-2xl border border-amber-200/70 bg-white/70 px-3 py-3 dark:border-amber-800/40 dark:bg-black/15"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-amber-200/80 text-[11px] font-semibold text-amber-800 dark:bg-amber-800/40 dark:text-amber-200">
                      {index + 1}
                    </div>
                    <div className="flex min-w-0 flex-col gap-1">
                      <h4 className="text-sm font-semibold leading-tight text-amber-950 dark:text-amber-100">
                        {stage.title}
                      </h4>
                      <p className="text-sm leading-relaxed text-foreground/80">
                        {stage.intent || '动作意图生成中。'}
                      </p>
                    </div>
                  </div>
                </section>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">正在整理阶段结构…</p>
          )}
        </div>
        <div ref={bottomRef} className="h-px" />
      </div>
    </div>
  )
}

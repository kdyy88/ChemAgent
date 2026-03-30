'use client'

import { memo } from 'react'
import { FlaskConical, AlertTriangle } from 'lucide-react'
import { Message, MessageContent } from '@/components/ui/message'
import { Loader } from '@/components/ui/loader'
import { ClarificationCard } from './ClarificationCard'
import { LipinskiCard } from './LipinskiCard'
import { ArtifactDispatcher } from './bubbles/ArtifactDispatcher'
import { ResearchThinking } from './bubbles/ResearchThinking'
import { parseLipinskiToolCalls } from '@/lib/chem-parsers'
import type { SSETurn } from '@/lib/sse-types'

// ── Main component ────────────────────────────────────────────────────────────

interface SSEMessageBubbleProps {
  turn: SSETurn
}

export const SSEMessageBubble = memo(function SSEMessageBubble({ turn }: SSEMessageBubbleProps) {
  const isStreaming = turn.isStreaming
  const showLoader = isStreaming && !turn.assistantText
  const lipinskiCards = parseLipinskiToolCalls(turn.toolCalls)

  return (
    <div className="flex flex-col gap-3">
      {/* User bubble — right-aligned */}
      <div className="flex justify-end">
        <Message className="max-w-[75%]">
          <MessageContent className="rounded-2xl bg-primary text-primary-foreground px-4 py-2.5 text-sm leading-relaxed shadow-sm">
            {turn.userMessage}
          </MessageContent>
        </Message>
      </div>

      {/* Agent response — left-aligned */}
      <Message className="items-start gap-2.5">
        {/* Avatar */}
        <div className="shrink-0 mt-0.5 flex h-7 w-7 items-center justify-center rounded-full bg-muted border" aria-hidden="true">
          <FlaskConical className="h-3.5 w-3.5 text-muted-foreground" />
        </div>

        {/* Content column */}
        <div className="flex flex-col gap-2 min-w-0 flex-1">
          <span className="text-xs font-medium text-muted-foreground">ChemAgent</span>

          {/* Thinking panel — auto-expands while streaming, collapses on completion */}
          {turn.thinkingSteps.length > 0 ? (
            <ResearchThinking steps={turn.thinkingSteps} isStreaming={isStreaming} />
          ) : (
            isStreaming && turn.activeNode === 'chem_agent' ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground animate-pulse">
                <span className="inline-block w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin" aria-hidden="true" />
                模型正在深度思考中，请稍候…
              </div>
            ) : null
          )}

          {/* HITL clarification card — shown when researcher needs user input */}
          {turn.pendingInterrupt && (
            <ClarificationCard
              interrupt={turn.pendingInterrupt}
              researchTopic={turn.userMessage}
            />
          )}

          {/* Assistant text */}
          {showLoader ? (
            <div className="rounded-2xl border bg-card px-4 py-3 shadow-sm">
              <Loader variant="typing" size="sm" />
            </div>
          ) : turn.assistantText ? (
            isStreaming ? (
              <div className="rounded-2xl border bg-card px-4 py-3 text-sm leading-relaxed shadow-sm">
                <span className="whitespace-pre-wrap">{turn.assistantText}</span>
                <Loader variant="typing" size="sm" className="mt-2" />
              </div>
            ) : (
              <MessageContent
                markdown
                className="rounded-2xl border bg-card px-4 py-3 text-sm leading-relaxed shadow-sm prose prose-sm dark:prose-invert max-w-none"
              >
                {turn.assistantText}
              </MessageContent>
            )
          ) : null}

          {/* Structured descriptor output rendered as Lipinski card */}
          {lipinskiCards.length > 0 && (
            <div className="flex flex-col gap-3 mt-1">
              {lipinskiCards.map((card, i) => (
                <LipinskiCard key={`lipinski-${turn.turnId}-${i}`} data={card} />
              ))}
            </div>
          )}

          {/* Artifacts */}
          <ArtifactDispatcher artifacts={turn.artifacts} />

          {/* Shadow errors */}
          {turn.shadowErrors.length > 0 && (
            <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 flex items-start gap-2 text-xs text-destructive">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <div className="flex flex-col gap-0.5">
                {turn.shadowErrors.map((e, i) => (
                  <span key={i}>{e.error}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </Message>
    </div>
  )
})

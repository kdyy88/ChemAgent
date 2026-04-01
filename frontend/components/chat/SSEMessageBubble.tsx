'use client'

import { memo, useEffect, useMemo, useState } from 'react'
import { FlaskConical, AlertTriangle } from 'lucide-react'
import { Message, MessageContent } from '@/components/ui/message'
import { Skeleton } from '@/components/ui/skeleton'
import { ClarificationCard } from './ClarificationCard'
import { LipinskiCard } from './LipinskiCard'
import { ArtifactDispatcher } from './bubbles/ArtifactDispatcher'
import { ResearchThinking } from './bubbles/ResearchThinking'
import { WebSourcesArtifact } from './bubbles/WebSourcesArtifact'
import { parseLipinskiToolCalls } from '@/lib/chem-parsers'
import type { SSETurn, WebSearchSourcesArtifact } from '@/lib/sse-types'

// ── Main component ────────────────────────────────────────────────────────────

interface SSEMessageBubbleProps {
  turn: SSETurn
}

export const SSEMessageBubble = memo(function SSEMessageBubble({ turn }: SSEMessageBubbleProps) {
  const isStreaming = turn.isStreaming
  const lipinskiCards = parseLipinskiToolCalls(turn.toolCalls)

  // Split artifacts: web sources show immediately; the rest are delayed
  const webSources = useMemo(
    () => turn.artifacts.filter((a): a is WebSearchSourcesArtifact => a.kind === 'web_search_sources'),
    [turn.artifacts],
  )
  const otherArtifacts = useMemo(
    () => turn.artifacts.filter((a) => a.kind !== 'web_search_sources'),
    [turn.artifacts],
  )

  // Planning phase: activeNode==='planner_node' fires BEFORE tasks arrive (via node_start).
  // This is the reliable signal to show the planning card skeleton.
  const isPlanning = isStreaming && turn.activeNode === 'planner_node'
  const showThinkingDots = isStreaming && turn.thinkingSteps.length === 0 && !isPlanning

  // ── Artifact reveal: 1 s delay + skeleton after streaming ends ──────────────
  const hasOtherArtifacts = otherArtifacts.length > 0 || lipinskiCards.length > 0
  const [artifactsReady, setArtifactsReady] = useState(false)

  useEffect(() => {
    if (!isStreaming && hasOtherArtifacts) {
      const t = setTimeout(() => setArtifactsReady(true), 1000)
      return () => clearTimeout(t)
    }
    if (isStreaming) setArtifactsReady(false)
  }, [isStreaming, hasOtherArtifacts])

  const showArtifactSkeleton = !isStreaming && hasOtherArtifacts && !artifactsReady
  const showArtifacts = artifactsReady
  // Web sources show immediately as soon as they arrive (no delay)
  const showWebSources = webSources.length > 0

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
          {turn.thinkingSteps.length > 0 && (
            <ResearchThinking steps={turn.thinkingSteps} isStreaming={isStreaming} webSources={webSources} />
          )}

          {/* Web sources fallback — when there are no thinking steps to embed into */}
          {showWebSources && turn.thinkingSteps.length === 0 && (
            <div className="flex flex-col gap-2">
              {webSources.map((src, i) => (
                <WebSourcesArtifact key={`ws-${i}`} artifact={src} />
              ))}
            </div>
          )}

          {/* Subtle thinking dots — only when truly nothing has arrived yet */}
          {showThinkingDots && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground py-0.5">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce [animation-delay:0ms]" aria-hidden="true" />
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce [animation-delay:120ms]" aria-hidden="true" />
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce [animation-delay:240ms]" aria-hidden="true" />
              <span className="ml-1 text-muted-foreground/70">Thinking…</span>
            </div>
          )}

          {/* Planning indicator — text-only, no card */}
          {isPlanning && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground py-0.5">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce [animation-delay:0ms]" aria-hidden="true" />
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce [animation-delay:120ms]" aria-hidden="true" />
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce [animation-delay:240ms]" aria-hidden="true" />
              <span className="ml-1 text-muted-foreground/70">Planning…</span>
            </div>
          )}

          {/* HITL clarification card — shown when researcher needs user input */}
          {turn.pendingInterrupt && (
            <ClarificationCard
              interrupt={turn.pendingInterrupt}
              researchTopic={turn.userMessage}
            />
          )}

          {/* Assistant text */}
          {turn.assistantText ? (
            isStreaming ? (
              <div className="rounded-2xl border bg-card px-4 py-3 text-sm leading-relaxed shadow-sm">
                <span className="whitespace-pre-wrap">{turn.assistantText}</span>
                <span className="inline-block w-3 h-3.5 border-l-2 border-primary ml-0.5 align-middle animate-[blink_1s_ease-in-out_infinite]" aria-hidden="true" />
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

          {/* Artifact skeleton — shown for 1s after streaming ends, before real artifacts fade in */}
          {showArtifactSkeleton && (
            <div className="flex flex-row flex-wrap gap-3 mt-1" aria-label="Loading results…">
              {otherArtifacts.map((_, i) => (
                <Skeleton key={`skel-${i}`} className="h-40 w-40 rounded-xl" />
              ))}
              {lipinskiCards.map((_, i) => (
                <Skeleton key={`lskel-${i}`} className="h-20 w-full rounded-xl" />
              ))}
            </div>
          )}

          {/* Real artifacts — revealed after 1 s delay */}
          {showArtifacts && lipinskiCards.length > 0 && (
            <div className="flex flex-col gap-3 mt-1">
              {lipinskiCards.map((card, i) => (
                <LipinskiCard key={`lipinski-${turn.turnId}-${i}`} data={card} />
              ))}
            </div>
          )}
          {showArtifacts && (
            <ArtifactDispatcher artifacts={otherArtifacts} />
          )}

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

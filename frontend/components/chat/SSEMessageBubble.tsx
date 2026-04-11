'use client'

import { memo, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, FlaskConical, LoaderCircle } from 'lucide-react'
import { Message, MessageContent } from '@/components/ui/message'
import { Skeleton } from '@/components/ui/skeleton'
import { ClarificationCard } from './ClarificationCard'
import { ApprovalCard } from './ApprovalCard'
import { PlanDraftStream } from './PlanDraftStream'
import { LipinskiCard } from './LipinskiCard'
import { SubAgentReportCard, type SubAgentOutput } from './SubAgentReportCard'
import { ArtifactDispatcher } from './bubbles/ArtifactDispatcher'
import { ResearchThinking } from './bubbles/ResearchThinking'
import { WebSourcesArtifact } from './bubbles/WebSourcesArtifact'
import { parseLipinskiToolCalls } from '@/lib/chem-parsers'
import { useUIStore } from '@/store/uiStore'
import type { SSETurn, WebSearchSourcesArtifact } from '@/lib/sse-types'

// ── Main component ────────────────────────────────────────────────────────────

interface SSEMessageBubbleProps {
  turn: SSETurn
}

export const SSEMessageBubble = memo(function SSEMessageBubble({ turn }: SSEMessageBubbleProps) {
  const isStreaming = turn.isStreaming
  const { appMode } = useUIStore()
  const isAgentMode = appMode === 'agent'
  const lipinskiCards = parseLipinskiToolCalls(turn.toolCalls)

  // Collect completed sub-agent tool call outputs for SubAgentReportCard.
  // Exclude plan_pending_approval — those are handled by ApprovalCard instead.
  const subAgentOutputs = useMemo<SubAgentOutput[]>(() => {
    return turn.toolCalls
      .filter((tc) => tc.tool === 'tool_run_sub_agent' && tc.done && tc.output != null)
      .map((tc) => tc.output as unknown as SubAgentOutput)
      .filter((o) => typeof o.status === 'string' && o.status !== 'plan_pending_approval')
  }, [turn.toolCalls])

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

  // ── Artifact reveal: 1 s delay + skeleton after streaming ends ──────────────
  const hasOtherArtifacts = otherArtifacts.length > 0 || lipinskiCards.length > 0
  const [artifactsReady, setArtifactsReady] = useState(false)
  const [streamElapsedSeconds, setStreamElapsedSeconds] = useState(0)

  useEffect(() => {
    if (!isStreaming && hasOtherArtifacts) {
      const t = setTimeout(() => setArtifactsReady(true), 1000)
      return () => clearTimeout(t)
    }
    if (isStreaming) setArtifactsReady(false)
  }, [isStreaming, hasOtherArtifacts])

  useEffect(() => {
    if (!isStreaming) {
      setStreamElapsedSeconds(0)
      return
    }

    const startedAt = Date.now()
    setStreamElapsedSeconds(0)

    const timer = window.setInterval(() => {
      setStreamElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)

    return () => window.clearInterval(timer)
  }, [isStreaming, turn.turnId])

  const showArtifactSkeleton = !isStreaming && hasOtherArtifacts && !artifactsReady && !isAgentMode
  const showArtifacts = artifactsReady && !isAgentMode
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

          {/* HITL clarification card — shown when researcher needs user input */}
          {turn.pendingInterrupt && (
            <ClarificationCard
              interrupt={turn.pendingInterrupt}
              researchTopic={turn.userMessage}
            />
          )}

          {/* Plan-mode live draft — streams while Pipeline Architect is thinking; 
               fades out when pendingApproval (ApprovalCard) takes over */}
          {turn.planDraftText && !turn.pendingApproval && (
            <PlanDraftStream text={turn.planDraftText} isStreaming={isStreaming} />
          )}

          {/* Hard-breakpoint approval card — shown before executing HEAVY_TOOLS */}
          {turn.pendingApproval && (
            <ApprovalCard approval={turn.pendingApproval} />
          )}

          {/* Sub-agent delegation result cards — one per completed tool_run_sub_agent call */}
          {!isStreaming && subAgentOutputs.length > 0 && (
            <div className="flex flex-col gap-2">
              {subAgentOutputs.map((o, i) => (
                <SubAgentReportCard key={`subagent-${turn.turnId}-${i}`} output={o} />
              ))}
            </div>
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

          {isStreaming && (
            <div className="flex items-center gap-2 rounded-full border border-border/70 bg-muted/45 px-3 py-1.5 text-xs text-muted-foreground/78 shadow-sm backdrop-blur-sm w-fit">
              <LoaderCircle className="h-3.5 w-3.5 animate-spin text-foreground/62" />
              <span className="font-medium text-foreground/70">
                {isPlanning ? 'Thinking · Planning…' : 'Thinking…'}
              </span>
              <span className="rounded-full bg-background/80 px-1.5 py-0.5 font-mono tabular-nums text-[10px] text-muted-foreground/72">
                {streamElapsedSeconds}s
              </span>
            </div>
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

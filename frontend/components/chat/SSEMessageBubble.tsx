'use client'

import { memo, useState } from 'react'
import { FlaskConical, Download, AlertTriangle } from 'lucide-react'
import { Message, MessageContent } from '@/components/ui/message'
import { Loader } from '@/components/ui/loader'
import { Button } from '@/components/ui/button'
import { Reasoning, ReasoningTrigger, ReasoningContent } from '@/components/ui/reasoning'
import { MoleculeCard } from './MoleculeCard'
import { ClarificationCard } from './ClarificationCard'
import type {
  SSETurn,
  SSEArtifactEvent,
  SSEThinking,
  FormatConversionArtifact,
  ConformerSdfArtifact,
  PdbqtFileArtifact,
} from '@/lib/sse-types'

// ── Researcher thinking panel (Claude-style) ─────────────────────────────────

function ResearchThinking({ steps, isStreaming }: { steps: SSEThinking[]; isStreaming: boolean }) {
  const [manualOpen, setManualOpen] = useState(true)
  const open = isStreaming ? true : manualOpen

  if (steps.length === 0) return null

  return (
    <Reasoning open={open} onOpenChange={setManualOpen} isStreaming={isStreaming}>
      <ReasoningTrigger className="text-xs text-muted-foreground hover:text-foreground font-medium transition-colors">
        {isStreaming ? (
          <span className="flex items-center gap-1">
            思维链生成中
            <span className="inline-flex gap-0.5">
              <span className="animate-bounce [animation-delay:0ms]">.</span>
              <span className="animate-bounce [animation-delay:150ms]">.</span>
              <span className="animate-bounce [animation-delay:300ms]">.</span>
            </span>
          </span>
        ) : (
          `已记录 ${steps.length} 条推理步骤`
        )}
      </ReasoningTrigger>
      <ReasoningContent
        className="mt-2 pl-3 border-l border-border flex flex-col gap-3"
        contentClassName="text-xs leading-relaxed whitespace-pre-wrap font-mono opacity-75"
      >
        {/* 修复：遍历渲染每一次 iteration 的思考内容 */}
        {steps.map((step, idx) => {
          const stepStreaming = isStreaming && step.done !== true && idx === steps.length - 1
          return (
            <div key={idx} className="relative">
              {step.text}
              {stepStreaming && (
                <span className="inline-block w-[2px] h-[1em] ml-0.5 bg-current align-middle animate-pulse" />
              )}
            </div>
          )
        })}
      </ReasoningContent>
    </Reasoning>
  )
}

// ── Text / download artifact card ─────────────────────────────────────────────

type TextArtifactEvent =
  | ConformerSdfArtifact
  | PdbqtFileArtifact
  | FormatConversionArtifact

function TextArtifactCard({ artifact }: { artifact: TextArtifactEvent }) {
  const ext =
    artifact.kind === 'pdbqt_file' ? 'pdbqt'
    : artifact.kind === 'conformer_sdf' ? 'sdf'
    : 'txt'

  const content =
    artifact.kind === 'conformer_sdf' ? artifact.sdf_content
    : artifact.kind === 'pdbqt_file' ? artifact.pdbqt_content
    : artifact.output

  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${artifact.title ?? artifact.kind}.${ext}`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="rounded-xl border bg-muted/40 overflow-hidden text-sm">
      <div className="flex items-center justify-between px-3 py-2 border-b bg-muted/60">
        <span className="font-medium text-muted-foreground truncate">
          {artifact.title ?? artifact.kind}
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 px-2 gap-1 text-xs"
          onClick={handleDownload}
        >
          <Download className="h-3.5 w-3.5" />
          .{ext}
        </Button>
      </div>
      <pre className="p-3 text-xs leading-relaxed overflow-auto max-h-48 font-mono whitespace-pre-wrap break-all">
        {content.slice(0, 2000)}
        {content.length > 2000 && '\n…（已截断）'}
      </pre>
    </div>
  )
}

// ── Artifact dispatcher ───────────────────────────────────────────────────────

function ArtifactItem({ artifact }: { artifact: SSEArtifactEvent }) {
  if (
    artifact.kind === 'molecule_image' ||
    artifact.kind === 'descriptor_structure_image' ||
    artifact.kind === 'highlighted_substructure'
  ) {
    return (
      <div className="w-[196px] shrink-0">
        <MoleculeCard image={artifact.image} title={artifact.title} />
      </div>
    )
  }

  return (
    <div className="w-full">
      <TextArtifactCard artifact={artifact as TextArtifactEvent} />
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface SSEMessageBubbleProps {
  turn: SSETurn
}

export const SSEMessageBubble = memo(function SSEMessageBubble({ turn }: SSEMessageBubbleProps) {
  const isStreaming = turn.isStreaming
  const showLoader = isStreaming && !turn.assistantText

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
        <div className="shrink-0 mt-0.5 flex h-7 w-7 items-center justify-center rounded-full bg-muted border">
          <FlaskConical className="h-3.5 w-3.5 text-muted-foreground" />
        </div>

        {/* Content column */}
        <div className="flex flex-col gap-2 min-w-0 flex-1">
          <span className="text-xs font-medium text-muted-foreground">ChemAgent</span>

          {/* Thinking panel — auto-expands while streaming, collapses on completion */}
          {turn.thinkingSteps.length > 0 && (
            <ResearchThinking steps={turn.thinkingSteps} isStreaming={isStreaming} />
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

          {/* Artifacts */}
          {turn.artifacts.length > 0 && (
            <div className="flex flex-row flex-wrap items-start gap-3 mt-1">
              {turn.artifacts.map((artifact, i) => (
                <ArtifactItem key={`${artifact.turn_id}-${i}`} artifact={artifact} />
              ))}
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

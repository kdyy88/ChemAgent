'use client'

import { memo, useState, useEffect } from 'react'
import { FlaskConical, Download, AlertTriangle, ExternalLink, Copy, Check, ChevronDown } from 'lucide-react'
import { Message, MessageContent } from '@/components/ui/message'
import { Loader } from '@/components/ui/loader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
import { Reasoning, ReasoningTrigger, ReasoningContent } from '@/components/ui/reasoning'
import { Source, SourceTrigger, SourceContent } from '@/components/ui/source'
import { MoleculeCard } from './MoleculeCard'
import { LipinskiCard } from './LipinskiCard'
import { ClarificationCard } from './ClarificationCard'
import type {
  SSETurn,
  SSEArtifactEvent,
  SSEThinking,
  DescriptorsArtifact,
  Conformer3DArtifact,
  PdbqtArtifact,
  FormatConversionArtifact,
} from '@/lib/sse-types'
import type { LipinskiResult } from '@/lib/chem-api'
import { cn } from '@/lib/utils'

// ── Descriptor adapter ────────────────────────────────────────────────────────

function descriptorsToLipinski(d: DescriptorsArtifact['data']): LipinskiResult {
  const desc = d.descriptors
  return {
    type: 'lipinski',
    is_valid: true,
    smiles: d.smiles ?? '',
    name: d.name ?? '',
    properties: {
      molecular_weight: {
        value: desc?.molecular_weight ?? 0,
        threshold: 500,
        pass: (desc?.molecular_weight ?? 0) <= 500,
      },
      log_p: {
        value: desc?.log_p ?? 0,
        threshold: 5,
        pass: (desc?.log_p ?? 0) <= 5,
      },
      h_bond_donors: {
        value: desc?.h_bond_donors ?? 0,
        threshold: 5,
        pass: (desc?.h_bond_donors ?? 0) <= 5,
      },
      h_bond_acceptors: {
        value: desc?.h_bond_acceptors ?? 0,
        threshold: 10,
        pass: (desc?.h_bond_acceptors ?? 0) <= 10,
      },
      tpsa: {
        value: desc?.tpsa ?? 0,
        threshold: 140,
        pass: (desc?.tpsa ?? 0) <= 140,
      },
    },
    lipinski_pass: d.lipinski?.pass ?? false,
    violations: d.lipinski?.violations ?? 0,
    structure_image: (d as Record<string, unknown>)['structure_image'] as string ?? '',
  }
}

// ── Tool badge color ──────────────────────────────────────────────────────────

function toolBadgeClass(toolName: string): string {
  if (toolName.startsWith('tool_pubchem') || toolName.startsWith('tool_web_search')) {
    return 'border-blue-300 text-blue-700 dark:border-blue-700 dark:text-blue-300'
  }
  if (toolName.startsWith('tool_render') || toolName.startsWith('tool_validate')) {
    return 'border-emerald-300 text-emerald-700 dark:border-emerald-700 dark:text-emerald-300'
  }
  if (toolName.startsWith('tool_compute') || toolName.startsWith('tool_murcko') || toolName.startsWith('tool_substructure')) {
    return 'border-orange-300 text-orange-700 dark:border-orange-700 dark:text-orange-300'
  }
  if (toolName.startsWith('tool_convert') || toolName.startsWith('tool_build') || toolName.startsWith('tool_prepare') || toolName.startsWith('tool_strip')) {
    return 'border-purple-300 text-purple-700 dark:border-purple-700 dark:text-purple-300'
  }
  return ''
}

// ── Researcher thinking panel (Claude-style) ─────────────────────────────────

function ResearchThinking({ steps, isStreaming }: { steps: SSEThinking[]; isStreaming: boolean }) {
  const [open, setOpen] = useState(true)

  // Re-open whenever streaming restarts (e.g. new turn)
  useEffect(() => {
    if (isStreaming) setOpen(true)
  }, [isStreaming])

  if (steps.length === 0) return null
  const latest = steps[steps.length - 1]
  // A step is still being streamed if: the turn is streaming AND the step has done=false (or done is absent for the last step during active streaming)
  const stepStreaming = isStreaming && latest.done !== true

  return (
    <Reasoning open={open} onOpenChange={setOpen} isStreaming={isStreaming}>
      <ReasoningTrigger className="text-xs text-muted-foreground hover:text-foreground font-medium transition-colors">
        {isStreaming ? (
          <span className="flex items-center gap-1">
            思考中
            <span className="inline-flex gap-0.5">
              <span className="animate-bounce [animation-delay:0ms]">.</span>
              <span className="animate-bounce [animation-delay:150ms]">.</span>
              <span className="animate-bounce [animation-delay:300ms]">.</span>
            </span>
          </span>
        ) : (
          `已完成 ${steps.length} 步推理`
        )}
      </ReasoningTrigger>
      <ReasoningContent
        className="mt-2 pl-3 border-l border-border"
        contentClassName="text-xs leading-relaxed whitespace-pre-wrap font-mono opacity-75"
      >
        {latest.text}
        {stepStreaming && (
          <span className="inline-block w-[2px] h-[1em] ml-0.5 bg-current align-middle animate-pulse" />
        )}
      </ReasoningContent>
    </Reasoning>
  )
}

// ── PubChem result card ───────────────────────────────────────────────────────

interface PubChemOutput {
  found?: boolean
  name?: string
  cid?: number
  canonical_smiles?: string
  isomeric_smiles?: string
  formula?: string
  molecular_weight?: number
  iupac_name?: string
  pubchem_url?: string
}

function PubChemCard({ output }: { output: PubChemOutput }) {
  const [copied, setCopied] = useState(false)
  if (!output.found) return null

  const smiles = output.canonical_smiles ?? output.isomeric_smiles ?? ''
  const copySmiles = () => {
    navigator.clipboard.writeText(smiles)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="rounded-xl border border-blue-200 dark:border-blue-900 bg-blue-50/50 dark:bg-blue-950/30 overflow-hidden text-sm">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-blue-200 dark:border-blue-900 bg-blue-100/60 dark:bg-blue-900/40">
        <span className="text-base">🔬</span>
        <span className="font-semibold text-blue-900 dark:text-blue-100 truncate">
          {output.name ?? 'PubChem'}
        </span>
        {output.pubchem_url && (
          <a
            href={output.pubchem_url}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1 text-xs shrink-0"
          >
            CID {output.cid}
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      <div className="px-3 py-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {output.formula && (
          <><span className="text-muted-foreground">分子式</span><span className="font-mono">{output.formula}</span></>
        )}
        {output.molecular_weight != null && (
          <><span className="text-muted-foreground">分子量</span><span>{Number(output.molecular_weight).toFixed(2)} g/mol</span></>
        )}
        {output.iupac_name && (
          <><span className="text-muted-foreground">IUPAC</span><span className="col-span-1 font-mono text-[11px] truncate" title={output.iupac_name}>{output.iupac_name}</span></>
        )}
      </div>
      {smiles && (
        <div className="px-3 pb-2.5 flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">SMILES</span>
          <code className="text-xs font-mono bg-muted/60 px-1.5 py-0.5 rounded truncate flex-1">{smiles}</code>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0 shrink-0"
            onClick={copySmiles}
          >
            {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
          </Button>
        </div>
      )}
    </div>
  )
}

// ── Web search results card ───────────────────────────────────────────────────

interface WebSearchResult {
  title: string
  url: string
  snippet: string
}
interface WebSearchOutput {
  status?: string
  query?: string
  results?: WebSearchResult[]
}

function WebSearchCard({ output }: { output: WebSearchOutput }) {
  const [open, setOpen] = useState(false)
  const results = output.results ?? []
  if (results.length === 0) return null

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors py-1 group">
          <span className="text-base">🌐</span>
          <span>查看来源 ({results.length})
            {output.query && (
              <span className="ml-1 opacity-60 truncate max-w-32 inline-block align-bottom">&ldquo;{output.query}&rdquo;</span>
            )}
          </span>
          <ChevronDown className={cn('h-3.5 w-3.5 transition-transform shrink-0', open && 'rotate-180')} />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-1.5 flex flex-col gap-1.5 pl-1 border-l-2 border-muted ml-1.5">
          {results.slice(0, 5).map((r, i) => (
            <Source key={i} href={r.url}>
              <div className="flex items-start gap-2 pl-2">
                <SourceTrigger showFavicon label={new URL(r.url).hostname.replace('www.', '')} />
                <div className="min-w-0">
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-medium hover:underline line-clamp-1"
                  >
                    {r.title}
                  </a>
                  <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{r.snippet}</p>
                </div>
              </div>
              <SourceContent title={r.title} description={r.snippet} />
            </Source>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// ── Tool output cards dispatcher ──────────────────────────────────────────────

type ToolCall = SSETurn['toolCalls'][number]

function ToolOutputCards({ toolCalls }: { toolCalls: ToolCall[] }) {
  const relevant = toolCalls.filter((tc) => tc.done && tc.output)
  if (relevant.length === 0) return null

  return (
    <div className="flex flex-col gap-2">
      {relevant.map((tc, i) => {
        if (tc.tool === 'tool_pubchem_lookup') {
          return <PubChemCard key={i} output={tc.output as PubChemOutput} />
        }
        if (tc.tool === 'tool_web_search') {
          return <WebSearchCard key={i} output={tc.output as WebSearchOutput} />
        }
        return null
      })}
    </div>
  )
}

// ── Text / download artifact card ─────────────────────────────────────────────

type TextArtifactEvent =
  | (Conformer3DArtifact     & { type: 'artifact'; session_id: string; turn_id: string })
  | (PdbqtArtifact           & { type: 'artifact'; session_id: string; turn_id: string })
  | (FormatConversionArtifact & { type: 'artifact'; session_id: string; turn_id: string })

function TextArtifactCard({ artifact }: { artifact: TextArtifactEvent }) {
  const ext =
    artifact.kind === 'pdbqt' ? 'pdbqt'
    : artifact.kind === 'conformer_3d' ? 'sdf'
    : 'txt'

  const handleDownload = () => {
    const blob = new Blob([artifact.data], { type: 'text/plain' })
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
        {artifact.data.slice(0, 2000)}
        {artifact.data.length > 2000 && '\n…（已截断）'}
      </pre>
    </div>
  )
}

// ── Artifact dispatcher ───────────────────────────────────────────────────────

function ArtifactItem({ artifact }: { artifact: SSEArtifactEvent }) {
  if (artifact.kind === 'structure_image' || artifact.kind === 'molecule_image') {
    return (
      <div className="w-[196px] shrink-0">
        <MoleculeCard image={artifact.data} title={artifact.title} />
      </div>
    )
  }

  if (artifact.kind === 'descriptors') {
    const lipinski = descriptorsToLipinski(artifact.data)
    return (
      <div className="w-full">
        <LipinskiCard data={lipinski} />
      </div>
    )
  }

  // conformer_3d, pdbqt, format_conversion
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

          {/* Status label while streaming */}
          {isStreaming && turn.statusLabel && (
            <div className="flex items-center gap-1.5">
              <Loader variant="typing" size="sm" className="shrink-0" />
              <span className="text-xs text-muted-foreground">{turn.statusLabel}</span>
            </div>
          )}

          {/* Thinking panel — auto-expands while streaming, collapses on completion */}
          {turn.thinkingSteps.length > 0 && (
            <ResearchThinking steps={turn.thinkingSteps} isStreaming={isStreaming} />
          )}

          {/* Tool call badges */}
          {turn.toolCalls.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {turn.toolCalls.map((tc, i) => (
                <Badge
                  key={i}
                  variant={tc.done ? 'secondary' : 'outline'}
                  className={cn(
                    'text-xs font-mono gap-1 transition-colors',
                    !tc.done && toolBadgeClass(tc.tool),
                  )}
                >
                  {tc.done
                    ? <span className="text-emerald-500">✓</span>
                    : <Loader variant="typing" size="sm" />}
                  {tc.tool.replace(/^tool_/, '')}
                </Badge>
              ))}
            </div>
          )}

          {/* Tool output cards — PubChem & web search */}
          <ToolOutputCards toolCalls={turn.toolCalls} />

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

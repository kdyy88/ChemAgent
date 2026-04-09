'use client'

import { useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  FileText,
  Layers,
  XCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { fetchScratchpad } from '@/lib/chem-api'
import { sseClient } from '@/services/sse-client'

export interface SubAgentOutput {
  status: 'ok' | 'protocol_error' | 'timeout' | 'error'
  mode: string
  sub_thread_id: string
  summary?: string
  completion?: {
    summary?: string
    produced_artifact_ids?: string[]
    advisory_active_smiles?: string
    metrics?: Record<string, unknown>
  }
  scratchpad_report_ref?: {
    scratchpad_id: string
    kind: string
    summary: string
    size_bytes: number
  }
  produced_artifacts?: unknown[]
  advisory_active_smiles?: string | null
}

interface SubAgentReportCardProps {
  output: SubAgentOutput
}

type LoadState = 'idle' | 'loading' | 'loaded' | 'error'

type ReportSection = {
  title: string
  lines: string[]
}

type ParsedReport = {
  sections: ReportSection[]
  copyText: string
}

type StructuredCompound = {
  name?: string
  pubchem_cid?: number | string
  canonical_smiles?: string
  bemis_murcko_scaffold_smiles?: string
  has_imidazole?: boolean
  imidazole_match_count?: number
}

type StructuredSummary = {
  shared_features?: unknown
  hinge_binder_typing_conservative?: unknown
}

type StructuredReportPayload = {
  summary?: string
  result?: string
  response?: string
  imidazole_smarts?: string
  compounds?: StructuredCompound[]
  structure_summary?: StructuredSummary
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item || '').trim()).filter(Boolean)
}

function clipText(value: string, limit: number): string {
  if (value.length <= limit) return value
  return `${value.slice(0, limit).trimEnd()}…`
}

function buildCompoundLine(compound: StructuredCompound, index: number): string {
  const name = String(compound.name || `化合物 ${index + 1}`).trim()
  const details: string[] = []

  if (compound.pubchem_cid) details.push(`PubChem CID ${compound.pubchem_cid}`)
  if (compound.has_imidazole === true) {
    details.push(`含咪唑环${compound.imidazole_match_count ? `（${compound.imidazole_match_count} 处）` : ''}`)
  } else if (compound.has_imidazole === false) {
    details.push('不含咪唑环')
  }
  if (compound.bemis_murcko_scaffold_smiles) {
    details.push(`Murcko scaffold ${clipText(compound.bemis_murcko_scaffold_smiles, 72)}`)
  }
  if (compound.canonical_smiles) {
    details.push(`SMILES ${clipText(compound.canonical_smiles, 88)}`)
  }

  return details.length > 0 ? `${name}：${details.join('；')}` : name
}

function parseStructuredReportContent(content: string): ParsedReport | null {
  const raw = content.trim()
  if (!raw.startsWith('{') && !raw.startsWith('[')) return null

  try {
    const parsed = JSON.parse(raw) as unknown
    if (!isRecord(parsed)) return null

    const payload = parsed as StructuredReportPayload
    const sections: ReportSection[] = []
    const overviewLines = [
      String(payload.summary || payload.result || payload.response || '').trim(),
      payload.imidazole_smarts ? `咪唑识别 SMARTS：${payload.imidazole_smarts}` : '',
    ].filter(Boolean)

    if (overviewLines.length > 0) {
      sections.push({ title: '结论摘要', lines: overviewLines })
    }

    if (Array.isArray(payload.compounds) && payload.compounds.length > 0) {
      sections.push({
        title: `已整理化合物（${payload.compounds.length} 个）`,
        lines: payload.compounds.map((compound, index) => buildCompoundLine(compound, index)),
      })
    }

    const structureSummary = isRecord(payload.structure_summary) ? payload.structure_summary : null
    if (structureSummary) {
      const sharedFeatures = toStringList(structureSummary.shared_features)
      const hingeBinderSummary = toStringList(structureSummary.hinge_binder_typing_conservative)

      if (sharedFeatures.length > 0) {
        sections.push({ title: '共同母核特征', lines: sharedFeatures })
      }
      if (hingeBinderSummary.length > 0) {
        sections.push({ title: '保守判断', lines: hingeBinderSummary })
      }
    }

    if (sections.length === 0) return null

    const copyText = sections
      .map((section) => [section.title, ...section.lines.map((line) => `- ${line}`)].join('\n'))
      .join('\n\n')

    return { sections, copyText }
  } catch {
    return null
  }
}

function StatusIcon({ status }: { status: SubAgentOutput['status'] }) {
  if (status === 'ok') return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
  if (status === 'timeout') return <Clock className="h-3.5 w-3.5 shrink-0 text-amber-500" />
  if (status === 'protocol_error') return <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" />
  return <XCircle className="h-3.5 w-3.5 shrink-0 text-destructive" />
}

function statusLabel(status: SubAgentOutput['status']): string {
  if (status === 'ok') return '完成'
  if (status === 'timeout') return '超时'
  if (status === 'protocol_error') return '协议错误'
  return '出错'
}

function modeLabel(mode: string): string {
  const map: Record<string, string> = {
    explore: '调研',
    plan: '规划',
    general: '执行',
    custom: '自定义',
  }
  return map[mode] ?? mode
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  return `${(n / 1024).toFixed(1)} KB`
}

export function SubAgentReportCard({ output }: SubAgentReportCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [loadState, setLoadState] = useState<LoadState>('idle')
  const [content, setContent] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const ref = output.scratchpad_report_ref
  const summary = output.completion?.summary || output.summary || ref?.summary || '（无摘要）'
  const artifactCount =
    output.completion?.produced_artifact_ids?.length ??
    (output.produced_artifacts as unknown[])?.length ??
    0
  const statusTone =
    output.status === 'ok'
      ? 'text-foreground/72'
      : output.status === 'timeout' || output.status === 'protocol_error'
        ? 'text-amber-700 dark:text-amber-300'
        : 'text-destructive'
        const parsedReport = content ? parseStructuredReportContent(content) : null

  async function handleExpand() {
    if (expanded) {
      setExpanded(false)
      return
    }
    setExpanded(true)
    if (!ref || loadState === 'loaded' || loadState === 'loading') return

    const sessionId = sseClient.sessionId ?? ''
    const subThreadId = output.sub_thread_id ?? ''
    if (!sessionId || !subThreadId) {
      setLoadState('error')
      setLoadError('缺少 session_id 或 sub_thread_id，无法读取报告。')
      return
    }

    setLoadState('loading')
    try {
      const entry = await fetchScratchpad(ref.scratchpad_id, sessionId, subThreadId)
      setContent(entry.content)
      setLoadState('loaded')
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err))
      setLoadState('error')
    }
  }

  async function handleCopy() {
    const textToCopy = parsedReport?.copyText || content
    if (!textToCopy) return
    await navigator.clipboard.writeText(textToCopy)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <div className="w-full px-1 pt-0.5 text-xs">
      <div className="relative pl-4">
        <span className="absolute left-0 top-[0.45rem] size-1.5 rounded-full bg-border" aria-hidden="true" />

        <div className="space-y-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[11px] leading-relaxed">
            <span className="font-medium text-foreground/74">子智能体</span>
            <span className="text-muted-foreground/60">{modeLabel(output.mode)}</span>
            <span className="inline-flex items-center gap-1">
              <StatusIcon status={output.status} />
              <span className={statusTone}>{statusLabel(output.status)}</span>
            </span>
            {artifactCount > 0 && (
              <span className="inline-flex items-center gap-1 text-muted-foreground/55">
                <Layers className="h-3 w-3" />
                {artifactCount}
              </span>
            )}
            {ref && <span className="text-muted-foreground/48">{formatBytes(ref.size_bytes)}</span>}
            {ref && (
              <button
                onClick={handleExpand}
                className="inline-flex items-center gap-0.5 text-muted-foreground/62 transition-colors hover:text-foreground/76"
                aria-label={expanded ? '收起报告' : '展开完整报告'}
              >
                <FileText className="h-3.5 w-3.5" />
                <span>{expanded ? '收起详情' : '查看详情'}</span>
                {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              </button>
            )}
          </div>

          <p className="text-[11px] leading-relaxed text-muted-foreground/76">{summary}</p>
        </div>
      </div>

      {expanded && ref && (
        <div className="mt-2 border-l border-border/70 pl-7">
          {loadState === 'loading' && (
            <div className="flex items-center gap-1.5 py-1 text-muted-foreground">
              <span className="inline-block h-1 w-1 rounded-full bg-muted-foreground animate-bounce [animation-delay:0ms]" />
              <span className="inline-block h-1 w-1 rounded-full bg-muted-foreground animate-bounce [animation-delay:100ms]" />
              <span className="inline-block h-1 w-1 rounded-full bg-muted-foreground animate-bounce [animation-delay:200ms]" />
              <span className="ml-1 text-[11px]">正在加载报告…</span>
            </div>
          )}

          {loadState === 'error' && (
            <div className="flex items-start gap-1.5 py-1 text-[11px] text-destructive">
              <XCircle className="mt-px h-3.5 w-3.5 shrink-0" />
              {loadError}
            </div>
          )}

          {loadState === 'loaded' && content !== null && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-muted-foreground/50">
                  {ref.scratchpad_id} · {ref.kind}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 gap-1 px-2 text-[10px] text-muted-foreground"
                  onClick={handleCopy}
                >
                  <Copy className="h-3 w-3" />
                  {copied ? '已复制' : '复制'}
                </Button>
              </div>
              {parsedReport ? (
                <div className="rounded-md border border-border/25 bg-muted/30 p-3">
                  <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1 text-[11px] leading-6 text-foreground/78">
                    {parsedReport.sections.map((section) => (
                      <section key={section.title} className="space-y-1.5">
                        <h4 className="text-[10px] font-medium tracking-[0.08em] text-muted-foreground/62">
                          {section.title}
                        </h4>
                        <div className="space-y-1">
                          {section.lines.map((line, index) => (
                            <p key={`${section.title}-${index}`} className="pl-3 text-[11px] leading-6 text-foreground/74">
                              <span className="-ml-3 mr-1 text-muted-foreground/45">•</span>
                              {line}
                            </p>
                          ))}
                        </div>
                      </section>
                    ))}
                  </div>
                </div>
              ) : (
                <pre className="max-h-[420px] overflow-x-auto overflow-y-auto whitespace-pre-wrap rounded-md border border-border/25 bg-muted/35 p-3 text-[11px] font-mono leading-relaxed">
                  {content}
                </pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

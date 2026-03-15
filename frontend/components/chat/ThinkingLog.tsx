'use client'

import { useState, useEffect, memo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronDown,
  ChevronRight,
  Terminal,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
} from 'lucide-react'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import type { Step, ToolMeta, TurnStatus } from '@/lib/types'

// ── Web search result cards ────────────────────────────────────────────────────
type SearchResult = { title: string; url: string; snippet: string }

function extractSearchResults(data: unknown): SearchResult[] {
  if (!data || typeof data !== 'object') return []
  const d = data as Record<string, unknown>
  if (!Array.isArray(d.results)) return []
  return (d.results as unknown[]).flatMap((r) => {
    if (!r || typeof r !== 'object') return []
    const item = r as Record<string, unknown>
    return [{ title: String(item.title ?? ''), url: String(item.url ?? ''), snippet: String(item.snippet ?? '') }]
  })
}

function hostname(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url.slice(0, 40) }
}

function WebSearchResults({ results }: { results: SearchResult[] }) {
  if (results.length === 0) return null
  return (
    <div className="flex flex-col gap-2 pt-1">
      {results.map((r, i) => (
        <a
          key={i}
          href={r.url}
          target="_blank"
          rel="noopener noreferrer"
          className="group block rounded-lg border border-stone-200 bg-white px-3 py-2 hover:border-stone-300 hover:bg-stone-50 transition-colors"
        >
          <p className="text-xs font-medium text-foreground group-hover:text-primary line-clamp-2 leading-snug">
            {r.title || '(无标题)'}
          </p>
          {r.snippet && (
            <p className="mt-0.5 text-[11px] text-muted-foreground line-clamp-2 leading-snug">
              {r.snippet}
            </p>
          )}
          <p className="mt-1 text-[10px] text-stone-400">{hostname(r.url)}</p>
        </a>
      ))}
    </div>
  )
}

// ── Sender badge ───────────────────────────────────────────────────────────────
const SENDER_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  Manager:           { bg: 'bg-blue-100',   text: 'text-blue-700',   label: 'Manager' },
  'Manager/Route':   { bg: 'bg-blue-100',   text: 'text-blue-700',   label: 'Manager' },
  'Manager/Synthesis':{ bg: 'bg-blue-100',  text: 'text-blue-700',   label: 'Manager' },
  Visualizer:        { bg: 'bg-green-100',  text: 'text-green-700',  label: 'Visualizer' },
  Researcher:        { bg: 'bg-purple-100', text: 'text-purple-700', label: 'Researcher' },
  Validator:         { bg: 'bg-amber-100',  text: 'text-amber-700',  label: 'Validator' },
}

function SenderBadge({ sender }: { sender: string }) {
  const s = SENDER_BADGE[sender] ?? { bg: 'bg-slate-100', text: 'text-slate-600', label: sender }
  return (
    <span className={`inline-flex items-center rounded px-1 py-0.5 text-[10px] font-semibold leading-none opacity-70 ${s.bg} ${s.text}`}>
      {s.label}
    </span>
  )
}

// ── Semantic text helpers ──────────────────────────────────────────────────────
function semanticAction(tool: string, args: Record<string, unknown>): string {
  switch (tool) {
    case 'web_search':
      return `正在查阅：「${String(args.query ?? '').slice(0, 60)}」`
    case 'get_smiles_by_name':
      return `正在解析化学名词：${String(args.chemical_name ?? '')}`
    case 'generate_2d_image_from_smiles':
      return `正在绘制 2D 结构：${String(args.name || args.smiles || '').slice(0, 40)}`
    default:
      return `正在执行：${tool.replace(/_/g, ' ')}`
  }
}

function semanticDone(tool: string, summary: string): string {
  const cleaned = summary.trim()
  switch (tool) {
    case 'web_search': {
      // "Found N result(s) for query '...': ..." → "找到 N 条结果"
      const m = cleaned.match(/Found (\d+) result/i)
      return m ? `找到 ${m[1]} 条结果` : (cleaned.split(':')[0].slice(0, 60) || '搜索完毕')
    }
    case 'get_smiles_by_name':
      return cleaned.slice(0, 60) || 'SMILES 获取成功'
    case 'generate_2d_image_from_smiles':
      return '结构图生成完毕'
    default:
      return cleaned.slice(0, 80) || '完成'
  }
}

// ── Merged tool step (pending → done/error, expandable) ───────────────────────
function MergedToolStep({
  step,
}: {
  step: Extract<Step, { kind: 'tool_call' }>
}) {
  const [expanded, setExpanded] = useState(false)
  const isPending = step.loadStatus === 'pending'
  const isError   = step.loadStatus === 'error'

  if (isPending) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-3 py-2">
        <Loader2 className="h-3.5 w-3.5 shrink-0 text-stone-400 animate-spin" />
        <div className="min-w-0 flex-1 text-xs text-stone-500">
          <div className="flex items-center gap-1.5 flex-wrap">
            {step.sender && <SenderBadge sender={step.sender} />}
            <span>{semanticAction(step.tool, step.args)}</span>
          </div>
        </div>
      </div>
    )
  }

  const borderColor = isError ? 'border-red-200' : 'border-stone-200'
  const bgColor     = isError ? 'bg-red-50'      : 'bg-stone-50'
  const textColor   = isError ? 'text-red-700'   : 'text-stone-600'
  const Icon = isError ? XCircle : CheckCircle2
  const iconColor = isError ? 'text-red-400' : 'text-stone-400'

  return (
    <div className={`rounded-md border ${borderColor} ${bgColor} overflow-hidden`}>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs ${textColor} hover:brightness-95 transition-all`}
      >
        <Icon className={`h-3.5 w-3.5 shrink-0 ${iconColor}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            {step.sender && <SenderBadge sender={step.sender} />}
            <span className="truncate">
              {isError
                ? `失败：${semanticAction(step.tool, step.args)}`
                : semanticDone(step.tool, step.summary ?? '')}
            </span>
          </div>
        </div>
        {expanded
          ? <ChevronDown  className="h-3 w-3 shrink-0 opacity-30" />
          : <ChevronRight className="h-3 w-3 shrink-0 opacity-30" />}
      </button>

      {expanded && (
        <div className={`border-t ${borderColor} px-3 py-2`}>
          {step.tool === 'web_search' ? (
            <WebSearchResults results={extractSearchResults(step.data)} />
          ) : (
            <p className="text-[11px] font-mono opacity-60 whitespace-pre-wrap break-all">
              {step.summary}
            </p>
          )}
          {step.retryHint && (
            <div className="mt-1 text-[11px] text-amber-600">↩ {step.retryHint}</div>
          )}
        </div>
      )}
    </div>
  )
}

function ErrorStep({ step }: { step: Extract<Step, { kind: 'error' }> }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />
      <p className="min-w-0 font-mono text-xs text-red-700">{step.content}</p>
    </div>
  )
}

function StepRow({ step }: { step: Step }) {
  if (step.kind === 'tool_call') return <MergedToolStep step={step} />
  if (step.kind === 'error')     return <ErrorStep      step={step} />
  // agent_reply and legacy tool_result are intentionally hidden
  return null
}

// ── Main component ─────────────────────────────────────────────────────────────
interface ThinkingLogProps {
  steps: Step[]
  status: TurnStatus
  startedAt: number
  finishedAt?: number
  toolCatalog: Record<string, ToolMeta>
  /** Live status label from the backend (e.g. "正在分析请求…") */
  statusMessage?: string
}

export const ThinkingLog = memo(function ThinkingLog({ steps, status, startedAt, finishedAt, statusMessage }: ThinkingLogProps) {
  const [open, setOpen] = useState(false)

  // While thinking: always open; after done: auto-collapse after 800 ms
  const effectiveOpen = status === 'thinking' && steps.length > 0 ? true : open

  useEffect(() => {
    if (status === 'done') {
      const t = setTimeout(() => setOpen(false), 800)
      return () => clearTimeout(t)
    }
  }, [status])

  // Count only visible steps for the header label
  const visibleSteps = steps.filter((s) => s.kind === 'tool_call' || s.kind === 'error')

  if (visibleSteps.length === 0 && status === 'thinking') {
    return (
      <div className="flex items-center gap-1.5 py-1 text-xs text-muted-foreground animate-pulse">
        <Terminal className="h-3.5 w-3.5 shrink-0" />
        <span>{statusMessage ?? '正在连接专家…'}</span>
      </div>
    )
  }

  if (visibleSteps.length === 0) return null

  const elapsed =
    finishedAt != null && startedAt > 0
      ? ((finishedAt - startedAt) / 1000).toFixed(1)
      : null

  return (
    <Collapsible open={effectiveOpen} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button className="flex items-center gap-1.5 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
          {effectiveOpen ? (
            <ChevronDown  className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0" />
          )}
          <Terminal className="h-3.5 w-3.5 shrink-0" />
          <span className="font-mono">
            {status === 'thinking' ? (
              <span className="flex items-center gap-1">
                思考中
                <span className="inline-flex gap-0.5">
                  <span className="animate-bounce [animation-delay:0ms]">.</span>
                  <span className="animate-bounce [animation-delay:150ms]">.</span>
                  <span className="animate-bounce [animation-delay:300ms]">.</span>
                </span>
              </span>
            ) : elapsed != null ? (
              `完成 ${visibleSteps.length} 个步骤 (${elapsed}s)`
            ) : (
              `${visibleSteps.length} 个步骤`
            )}
          </span>
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent forceMount>
        <AnimatePresence initial={false}>
          {effectiveOpen && (
            <motion.div
              key="steps-content"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.22, ease: 'easeInOut' }}
              className="overflow-hidden"
            >
              <div className="mt-1.5 flex flex-col gap-1.5 max-h-80 overflow-y-auto pr-0.5">
                <AnimatePresence initial={false}>
                  {steps.map((step, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.15 }}
                    >
                      <StepRow step={step} />
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </CollapsibleContent>
    </Collapsible>
  )
})


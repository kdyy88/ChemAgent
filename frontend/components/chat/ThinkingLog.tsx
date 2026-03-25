'use client'

import { memo, useState, useEffect } from 'react'
import {
  Terminal,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  ChainOfThought,
  ChainOfThoughtStep,
  ChainOfThoughtTrigger,
  ChainOfThoughtContent,
  ChainOfThoughtItem,
} from '@/components/ui/chain-of-thought'
import { Steps, StepsTrigger, StepsContent } from '@/components/ui/steps'
import { Source, SourceTrigger, SourceContent } from '@/components/ui/source'
import { TodoChecklist, parseTodoLines } from './TodoChecklist'
import { ReasoningBlock } from './ReasoningBlock'
import type { Step, TurnStatus } from '@/lib/types'

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

function WebSearchResults({ results }: { results: SearchResult[] }) {
  if (results.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1.5 pt-1">
      {results.map((r, i) => (
        <Source key={i} href={r.url}>
          <SourceTrigger label={r.title || undefined} showFavicon />
          <SourceContent title={r.title || '(无标题)'} description={r.snippet} />
        </Source>
      ))}
    </div>
  )
}

// ── Sender badge ───────────────────────────────────────────────────────────────
const SENDER_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  Manager:            { bg: 'bg-blue-100',   text: 'text-blue-700',   label: 'Manager' },
  'Manager/Route':    { bg: 'bg-blue-100',   text: 'text-blue-700',   label: 'Manager' },
  'Manager/Synthesis':{ bg: 'bg-blue-100',   text: 'text-blue-700',   label: 'Manager' },
  Visualizer:         { bg: 'bg-green-100',  text: 'text-green-700',  label: 'Visualizer' },
  Researcher:         { bg: 'bg-purple-100', text: 'text-purple-700', label: 'Researcher' },
  Validator:          { bg: 'bg-amber-100',  text: 'text-amber-700',  label: 'Validator' },
  Analyst:            { bg: 'bg-orange-100', text: 'text-orange-700', label: 'Analyst' },
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
    case 'get_molecule_smiles':
      return `正在检索 ${String(args.name ?? '化合物').slice(0, 30)} 的 SMILES`
    case 'analyze_molecule_from_smiles':
      return `正在计算分子性质：${String(args.name || args.smiles || '').slice(0, 40)}`
    case 'draw_molecules_by_name':
      return `正在绘制：${String(args.chemical_names ?? '').slice(0, 60)}`
    case 'identify_scaffolds':
      return `正在提取骨架：${String(args.name || args.smiles || '').slice(0, 40)}`
    case 'check_pains':
      return `正在检测 PAINS 结构警报`
    case 'compute_similarity':
      return `正在计算分子相似度`
    default:
      return `正在执行：${tool.replace(/_/g, ' ')}`
  }
}

function semanticDone(tool: string, summary: string): string {
  // If the summary looks like raw JSON from _slim_response, try to extract
  // the human-readable summary field from it.
  let cleaned = summary.trim()
  if (cleaned.startsWith('{')) {
    try {
      const parsed = JSON.parse(cleaned) as Record<string, unknown>
      if (typeof parsed.summary === 'string') cleaned = parsed.summary
    } catch { /* use original */ }
  }

  switch (tool) {
    case 'web_search': {
      const m = cleaned.match(/Found (\d+) result/i)
      return m ? `找到 ${m[1]} 条结果` : (cleaned.split(':')[0].slice(0, 60) || '搜索完毕')
    }
    case 'get_molecule_smiles':
      return cleaned.slice(0, 80) || 'SMILES 检索完成'
    case 'analyze_molecule_from_smiles':
      return '分子性质计算完毕'
    case 'draw_molecules_by_name':
      return cleaned.slice(0, 80) || '结构图绘制完成'
    case 'identify_scaffolds':
      return cleaned.slice(0, 80) || '骨架提取完成'
    case 'check_pains':
      return cleaned.slice(0, 80) || 'PAINS 检测完成'
    case 'compute_similarity':
      return cleaned.slice(0, 80) || '相似度计算完成'
    default:
      return cleaned.slice(0, 80) || '完成'
  }
}

// ── Compact todo (Claude/Cursor style) ────────────────────────────────────────
export function CompactTodoStep({ todo }: { todo: string }) {
  const { items, hasCheckboxes } = parseTodoLines(todo)

  if (!hasCheckboxes || items.length === 0) {
    return (
      <ChainOfThoughtStep>
        <ChainOfThoughtTrigger
          leftIcon={<CheckCircle2 className="h-3.5 w-3.5 text-green-400" />}
          className="text-xs text-green-700 dark:text-green-400"
        >
          任务清单
        </ChainOfThoughtTrigger>
      </ChainOfThoughtStep>
    )
  }

  const checkedCount = items.filter((i) => i.checked).length
  const total = items.length

  return (
    <div className="flex flex-col gap-0 py-0.5">
      {/* Header row showing progress count */}
      <div className="flex items-center gap-1.5 px-2 pb-0.5 text-[11px] text-muted-foreground">
        <CheckCircle2 className="h-3 w-3 shrink-0 text-green-500" />
        <span className="font-medium">任务进度 ({checkedCount}/{total})</span>
      </div>
      {/* Inline compact rows: one line per task, icon + truncated label */}
      <div className="flex flex-col gap-0">
        {items.map((item, i) => (
          <div
            key={i}
            className={cn(
              'flex items-center gap-1.5 pl-6 pr-2 py-[1px] text-[11px] leading-snug',
              item.checked ? 'text-muted-foreground/60' : 'text-muted-foreground',
            )}
          >
            {item.checked ? (
              <CheckCircle2 className="h-3 w-3 shrink-0 text-green-500 opacity-80" />
            ) : (
              <div className="h-3 w-3 shrink-0 rounded-full border border-muted-foreground/35" />
            )}
            <span
              className={cn(
                'truncate',
                item.checked && 'line-through opacity-60',
              )}
              title={item.label}
            >
              {item.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Tool step ─────────────────────────────────────────────────────────────────
function ToolStep({ step }: { step: Extract<Step, { kind: 'tool_call' }> }) {
  const isPending = step.loadStatus === 'pending'
  const isError   = step.loadStatus === 'error'

  const icon = isPending ? (
    <Loader2 className="h-3.5 w-3.5 text-stone-400 animate-spin" />
  ) : isError ? (
    <XCircle className="h-3.5 w-3.5 text-red-400" />
  ) : (
    <CheckCircle2 className="h-3.5 w-3.5 text-stone-400" />
  )

  const label = isPending
    ? semanticAction(step.tool, step.args)
    : isError
    ? `失败：${semanticAction(step.tool, step.args)}`
    : semanticDone(step.tool, step.summary ?? '')

  const hasContent = !isPending

  return (
    <ChainOfThoughtStep disabled={isPending}>
      <ChainOfThoughtTrigger
        leftIcon={icon}
        swapIconOnHover={hasContent}
        className={cn('text-xs', isError && 'text-red-600')}
      >
        <span className="flex items-center gap-1.5 flex-wrap min-w-0">
          {step.sender && <SenderBadge sender={step.sender} />}
          <span className={cn('truncate', isPending && 'text-stone-500')}>{label}</span>
        </span>
      </ChainOfThoughtTrigger>
      {hasContent && (
        <ChainOfThoughtContent>
          <ChainOfThoughtItem>
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
          </ChainOfThoughtItem>
        </ChainOfThoughtContent>
      )}
    </ChainOfThoughtStep>
  )
}

// ── Error step ────────────────────────────────────────────────────────────────
function ErrorStepRow({ step }: { step: Extract<Step, { kind: 'error' }> }) {
  const long = step.content.length > 80
  return (
    <ChainOfThoughtStep>
      <ChainOfThoughtTrigger
        leftIcon={<AlertTriangle className="h-3.5 w-3.5 text-red-500" />}
        swapIconOnHover={long}
        className="text-xs text-red-700"
      >
        {step.content.slice(0, 80)}{long ? '…' : ''}
      </ChainOfThoughtTrigger>
      {long && (
        <ChainOfThoughtContent>
          <ChainOfThoughtItem className="font-mono text-[11px] text-red-700 break-all whitespace-pre-wrap">
            {step.content}
          </ChainOfThoughtItem>
        </ChainOfThoughtContent>
      )}
    </ChainOfThoughtStep>
  )
}

function StepRow({ step }: { step: Step }) {
  if (step.kind === 'tool_call') return <ToolStep step={step} />
  if (step.kind === 'error')     return <ErrorStepRow step={step} />
  if (step.kind === 'plan') {
    return (
      <ChainOfThoughtStep>
        <ChainOfThoughtTrigger
          leftIcon={<CheckCircle2 className="h-3.5 w-3.5 text-blue-400" />}
          swapIconOnHover
          className="text-xs text-blue-700 dark:text-blue-400"
        >
          执行计划已生成
        </ChainOfThoughtTrigger>
        <ChainOfThoughtContent>
          <ChainOfThoughtItem className="font-mono text-[11px] whitespace-pre-wrap break-all">
            {step.plan}
          </ChainOfThoughtItem>
        </ChainOfThoughtContent>
      </ChainOfThoughtStep>
    )
  }
  if (step.kind === 'todo') return null
  return null
}

// ── Main component ─────────────────────────────────────────────────────────────
interface ThinkingLogProps {
  steps: Step[]
  status: TurnStatus
  startedAt: number
  finishedAt?: number
  statusMessage?: string
}

export const ThinkingLog = memo(function ThinkingLog({
  steps,
  status,
  startedAt,
  finishedAt,
  statusMessage,
}: ThinkingLogProps) {
  const isThinking = status === 'thinking' || status === 'awaiting_approval'
  // Exclude 'todo' steps — CompactTodoStep renders above ChatInput
  // Exclude 'thinking' steps — rendered separately above the chain-of-thought
  // Include 'plan' steps — show "执行计划已生成" badge in the thinking log
  const visibleSteps = steps.filter((s) => s.kind === 'tool_call' || s.kind === 'error' || s.kind === 'plan')
  const thinkingStep = steps.find((s) => s.kind === 'thinking') as Extract<Step, { kind: 'thinking' }> | undefined
  const [open, setOpen] = useState(true)

  // Keep expanded while thinking; allow user to collapse once done
  useEffect(() => {
    if (isThinking) setOpen(true)
  }, [isThinking])

  if (visibleSteps.length === 0 && !thinkingStep && isThinking) {
    return (
      <div className="flex items-center gap-1.5 py-1 text-xs text-muted-foreground animate-pulse">
        <Terminal className="h-3.5 w-3.5 shrink-0" />
        <span>{statusMessage ?? '正在连接专家…'}</span>
      </div>
    )
  }

  if (visibleSteps.length === 0 && !thinkingStep) return null

  const elapsed =
    finishedAt != null && startedAt > 0
      ? ((finishedAt - startedAt) / 1000).toFixed(1)
      : null

  return (
    <div className="flex flex-col gap-1.5">
      {thinkingStep && (
        <ReasoningBlock
          content={thinkingStep.content}
          isStreaming={isThinking}
        />
      )}
      {visibleSteps.length > 0 && (
        <Steps open={open} onOpenChange={setOpen}>
          <StepsTrigger
            leftIcon={<Terminal className="h-3.5 w-3.5 shrink-0" />}
            swapIconOnHover={!isThinking}
            className="text-xs text-muted-foreground font-mono"
          >
            {isThinking ? (
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
          </StepsTrigger>
          <StepsContent>
            <ChainOfThought className="max-h-80 overflow-y-auto pr-0.5">
              {steps.map((step, i) => (
                <StepRow key={i} step={step} />
              ))}
            </ChainOfThought>
          </StepsContent>
        </Steps>
      )}
    </div>
  )
})

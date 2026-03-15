'use client'

import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronDown,
  ChevronRight,
  Terminal,
  Wrench,
  CheckCircle2,
  XCircle,
  MessageSquare,
  AlertTriangle,
} from 'lucide-react'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import type { Step, ToolMeta, TurnStatus } from '@/lib/types'

// ── Sender badge colour map ────────────────────────────────────────────────────
// Pre-wired for current and future agents; falls back to slate for unknowns.
const SENDER_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  'Manager':          { bg: 'bg-blue-100',   text: 'text-blue-700',   label: 'Manager' },
  'Manager/Route':    { bg: 'bg-blue-100',   text: 'text-blue-700',   label: 'Manager' },
  'Manager/Synthesis':{ bg: 'bg-blue-100',   text: 'text-blue-700',   label: 'Manager' },
  'Visualizer':       { bg: 'bg-green-100',  text: 'text-green-700',  label: 'Visualizer' },
  'Researcher':       { bg: 'bg-purple-100', text: 'text-purple-700', label: 'Researcher' },
  'Validator':        { bg: 'bg-amber-100',  text: 'text-amber-700',  label: 'Validator' },
}

function SenderBadge({ sender }: { sender: string }) {
  const style = SENDER_BADGE[sender] ?? { bg: 'bg-slate-100', text: 'text-slate-600', label: sender }
  return (
    <span
      className={`inline-flex items-center rounded px-1 py-0.5 text-[10px] font-semibold leading-none opacity-70 ${
        style.bg
      } ${style.text}`}
    >
      {style.label}
    </span>
  )
}

const toolLabel = (name: string, toolCatalog: Record<string, ToolMeta>) =>
  toolCatalog[name]?.displayName ?? name.replace(/_/g, ' ')

// ── Truncate long strings (SMILES etc.) ───────────────────────────────────────
const trunc = (s: string, max = 80) =>
  s.length > max ? s.slice(0, max) + '…' : s

// ── Individual step renderers ─────────────────────────────────────────────────
function ToolCallStep({
  step,
  toolCatalog,
}: {
  step: Extract<Step, { kind: 'tool_call' }>
  toolCatalog: Record<string, ToolMeta>
}) {
  const argEntries = Object.entries(step.args)
  return (
    <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
      <Wrench className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
      <div className="min-w-0 flex-1 text-xs">
        <div className="flex items-center gap-1.5 flex-wrap">
          {step.sender && <SenderBadge sender={step.sender} />}
          <span className="font-medium text-amber-800">{toolLabel(step.tool, toolCatalog)}</span>
        </div>
        {argEntries.length > 0 && (
          <div className="mt-0.5 font-mono text-amber-700">
            {argEntries.map(([k, v]) => (
              <div key={k}>
                <span className="opacity-60">{k}: </span>
                <span>&quot;{trunc(String(v), 60)}&quot;</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function ToolResultStep({
  step,
  toolCatalog,
}: {
  step: Extract<Step, { kind: 'tool_result' }>
  toolCatalog: Record<string, ToolMeta>
}) {
  return step.status === 'success' ? (
    <div className="flex items-start gap-2 rounded-md border border-green-200 bg-green-50 px-3 py-2">
      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-600" />
      <div className="min-w-0 flex-1 text-xs text-green-800">
        <div className="flex items-center gap-1.5 flex-wrap">
          {step.sender && <SenderBadge sender={step.sender} />}
          <p className="font-medium">{toolLabel(step.tool, toolCatalog)}</p>
        </div>
        <p>{trunc(step.summary, 140)}</p>
      </div>
    </div>
  ) : (
    <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2">
      <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600" />
      <div className="min-w-0 flex-1 text-xs text-red-800">
        <div className="flex items-center gap-1.5 flex-wrap">
          {step.sender && <SenderBadge sender={step.sender} />}
          <p className="font-medium">{toolLabel(step.tool, toolCatalog)}</p>
        </div>
        <p>{trunc(step.summary, 140)}</p>
        {step.retryHint && <p className="mt-1 opacity-80">Retry hint: {trunc(step.retryHint, 120)}</p>}
      </div>
    </div>
  )
}

function AgentReplyStep({
  step,
}: {
  step: Extract<Step, { kind: 'agent_reply' }>
}) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2">
      <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-600" />
      <div className="min-w-0 flex-1 text-xs text-blue-800">
        {step.sender && (
          <div className="mb-0.5">
            <SenderBadge sender={step.sender} />
          </div>
        )}
        <p>{step.content}</p>
      </div>
    </div>
  )
}

function ErrorStep({ step }: { step: Extract<Step, { kind: 'error' }> }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600" />
      <p className="min-w-0 font-mono text-xs text-red-800">{step.content}</p>
    </div>
  )
}

function StepRow({
  step,
  toolCatalog,
}: {
  step: Step
  toolCatalog: Record<string, ToolMeta>
}) {
  switch (step.kind) {
    case 'tool_call':
      return <ToolCallStep step={step} toolCatalog={toolCatalog} />
    case 'tool_result':
      return <ToolResultStep step={step} toolCatalog={toolCatalog} />
    case 'agent_reply': return <AgentReplyStep step={step} />
    case 'error':       return <ErrorStep      step={step} />
  }
}

// ── Main component ────────────────────────────────────────────────────────────
interface ThinkingLogProps {
  steps: Step[]
  status: TurnStatus
  startedAt: number
  finishedAt?: number
  toolCatalog: Record<string, ToolMeta>
}

export function ThinkingLog({ steps, status, startedAt, finishedAt, toolCatalog }: ThinkingLogProps) {
  const [open, setOpen] = useState(false)
  const effectiveOpen = status === 'thinking' && steps.length > 0 ? true : open

  // Auto-collapse 800 ms after the turn finishes
  useEffect(() => {
    if (status === 'done') {
      const t = setTimeout(() => setOpen(false), 800)
      return () => clearTimeout(t)
    }
  }, [status])

  // Before any steps arrive — show a minimal "connecting" indicator
  if (steps.length === 0 && status === 'thinking') {
    return (
      <div className="flex items-center gap-1.5 py-1 text-xs text-muted-foreground animate-pulse">
        <Terminal className="h-3.5 w-3.5 shrink-0" />
        <span>Connecting to agent…</span>
      </div>
    )
  }

  if (steps.length === 0) return null

  const elapsed =
    finishedAt != null && startedAt > 0
      ? ((finishedAt - startedAt) / 1000).toFixed(1)
      : null

  return (
    <Collapsible open={effectiveOpen} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button className="flex items-center gap-1.5 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0" />
          )}
          <Terminal className="h-3.5 w-3.5 shrink-0" />
          <span className="font-mono">
            {status === 'thinking' ? (
              <span className="flex items-center gap-1">
                Reasoning
                <span className="inline-flex gap-0.5">
                  <span className="animate-bounce [animation-delay:0ms]">.</span>
                  <span className="animate-bounce [animation-delay:150ms]">.</span>
                  <span className="animate-bounce [animation-delay:300ms]">.</span>
                </span>
              </span>
            ) : elapsed != null ? (
              `查看推理过程 (已耗时 ${elapsed}s)`
            ) : (
              `查看推理过程 (${steps.length} steps)`
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
                      transition={{ duration: 0.15, delay: 0 }}
                    >
                      <StepRow step={step} toolCatalog={toolCatalog} />
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
}

'use client'

/**
 * ApprovalCard — Heavy-Tool HITL UI (Hard Breakpoint tier)
 *
 * Rendered when LangGraph pauses on a HEAVY_TOOLS interrupt and demands user
 * approval before executing an expensive computation.  The user may:
 *   • Approve  — run the tool exactly as the LLM planned.
 *   • Reject   — cancel; Agent receives a "rejected" ToolMessage and will
 *                re-plan.
 *   • Modify   — edit the JSON args directly, then approve the patched call.
 *
 * Design: resolves from the same amber palette as ClarificationCard but uses
 * a deeper warning treatment (orange border, shield icon) to differentiate
 * the hard-breakpoint tier from the softer clarification tier.
 */

import { useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { SSEPendingApproval } from '@/lib/sse-types'
import { useSseStore } from '@/store/sseStore'

interface ApprovalCardProps {
  approval: SSEPendingApproval
}

const TOOL_LABELS: Record<string, string> = {
  tool_build_3d_conformer: '生成三维构象',
  tool_docking_simulation: '分子对接模拟',
  tool_virtual_screening: '虚拟筛选',
}

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name.replace('tool_', '').replace(/_/g, ' ')
}

export function ApprovalCard({ approval }: ApprovalCardProps) {
  const { approveToolCall, isStreaming } = useSseStore()
  const [argsJson, setArgsJson] = useState(
    () => JSON.stringify(approval.args, null, 2)
  )
  const [parseError, setParseError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)

  const isDisabled = isStreaming || submitted

  function parseArgs(): Record<string, unknown> | null {
    try {
      const parsed = JSON.parse(argsJson)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setParseError('参数必须是一个 JSON 对象')
        return null
      }
      setParseError(null)
      return parsed as Record<string, unknown>
    } catch (e) {
      setParseError(`JSON 格式错误：${(e as Error).message}`)
      return null
    }
  }

  async function handleApprove() {
    if (isDisabled) return
    const args = parseArgs()
    if (!args) return
    setSubmitted(true)
    await approveToolCall('approve', args)
  }

  async function handleModify() {
    if (isDisabled) return
    const args = parseArgs()
    if (!args) return
    setSubmitted(true)
    await approveToolCall('modify', args)
  }

  async function handleReject() {
    if (isDisabled) return
    setSubmitted(true)
    await approveToolCall('reject')
  }

  const label = toolLabel(approval.tool_name)

  return (
    <div className="rounded-2xl border border-orange-300 bg-orange-50 dark:border-orange-700/50 dark:bg-orange-950/20 px-4 py-3 flex flex-col gap-3 shadow-sm">
      {/* Header */}
      <div className="flex items-start gap-2">
        <ShieldAlert className="h-4 w-4 text-orange-500 shrink-0 mt-0.5" />
        <div className="flex flex-col gap-0.5">
          <span className="text-xs font-semibold text-orange-700 dark:text-orange-400">
            高耗时操作 — 需要您的授权
          </span>
          <p className="text-sm text-foreground/90 leading-relaxed">
            Agent 计划执行 <span className="font-medium">{label}</span>，请确认参数后再继续。
          </p>
        </div>
      </div>

      {/* Editable args */}
      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">调用参数（可直接编辑）</span>
        <Textarea
          value={argsJson}
          onChange={(e) => {
            setArgsJson(e.target.value)
            setParseError(null)
          }}
          disabled={isDisabled}
          rows={Math.min(12, argsJson.split('\n').length + 1)}
          className="font-mono text-xs resize-none bg-white/60 dark:bg-black/20 border-orange-200 dark:border-orange-800/40 focus-visible:ring-orange-400"
          spellCheck={false}
        />
        {parseError && (
          <p className="text-xs text-destructive">{parseError}</p>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={isDisabled}
          className="h-7 text-xs border-orange-300 hover:bg-orange-100 dark:border-orange-700 dark:hover:bg-orange-900/40 text-destructive hover:text-destructive"
          onClick={handleReject}
        >
          拒绝执行
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={isDisabled}
          className="h-7 text-xs border-orange-300 hover:bg-orange-100 dark:border-orange-700 dark:hover:bg-orange-900/40"
          onClick={handleModify}
        >
          修改后执行
        </Button>
        <Button
          size="sm"
          disabled={isDisabled}
          className="h-7 text-xs bg-orange-500 hover:bg-orange-600 text-white"
          onClick={handleApprove}
        >
          确认执行
        </Button>
      </div>
    </div>
  )
}

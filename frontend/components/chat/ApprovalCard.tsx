'use client'

import { useEffect, useState } from 'react'
import { ClipboardPenLine, FilePenLine, ShieldAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { fetchPlanDocument } from '@/lib/artifact-api'
import type { SSEPendingApproval } from '@/lib/sse-types'
import { sseClient } from '@/services/sse-client'
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
  const [argsJson, setArgsJson] = useState('')
  const [planContent, setPlanContent] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isLoadingPlan, setIsLoadingPlan] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const isDisabled = isStreaming || submitted

  useEffect(() => {
    setSubmitted(false)
    setParseError(null)

    if (approval.kind === 'tool') {
      setArgsJson(JSON.stringify(approval.args, null, 2))
      setPlanContent('')
      setLoadError(null)
      return
    }

    setArgsJson('')
    setPlanContent(approval.content ?? '')
    setLoadError(null)
  }, [approval])

  useEffect(() => {
    if (approval.kind !== 'plan' || approval.content) return

    const sessionId = sseClient.sessionId
    if (!sessionId) {
      setLoadError('无法定位当前会话，暂时无法加载计划正文。')
      return
    }

    let cancelled = false
    setIsLoadingPlan(true)
    setLoadError(null)

    void fetchPlanDocument(sessionId, approval.plan_id)
      .then((document) => {
        if (cancelled) return
        setPlanContent(document.content)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setLoadError(error instanceof Error ? error.message : '计划正文加载失败')
      })
      .finally(() => {
        if (cancelled) return
        setIsLoadingPlan(false)
      })

    return () => {
      cancelled = true
    }
  }, [approval])

  function parseArgs(): Record<string, unknown> | null {
    try {
      const parsed = JSON.parse(argsJson)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setParseError('参数必须是一个 JSON 对象')
        return null
      }
      setParseError(null)
      return parsed as Record<string, unknown>
    } catch (error) {
      setParseError(`JSON 格式错误：${(error as Error).message}`)
      return null
    }
  }

  async function handleApprove() {
    if (isDisabled) return
    setSubmitted(true)

    if (approval.kind === 'plan') {
      await approveToolCall('approve')
      return
    }

    const args = parseArgs()
    if (!args) {
      setSubmitted(false)
      return
    }
    await approveToolCall('approve', args)
  }

  async function handleModify() {
    if (isDisabled) return
    setSubmitted(true)

    if (approval.kind === 'plan') {
      const content = planContent.trim()
      if (!content) {
        setParseError('计划正文不能为空')
        setSubmitted(false)
        return
      }
      await approveToolCall('modify', { content })
      return
    }

    const args = parseArgs()
    if (!args) {
      setSubmitted(false)
      return
    }
    await approveToolCall('modify', args)
  }

  async function handleReject() {
    if (isDisabled) return
    setSubmitted(true)
    await approveToolCall('reject')
  }

  if (approval.kind === 'plan') {
    return (
      <div className="flex flex-col gap-3 rounded-3xl border border-amber-300 bg-[linear-gradient(180deg,rgba(255,251,235,0.96),rgba(255,247,214,0.88))] px-4 py-4 shadow-sm dark:border-amber-800/60 dark:bg-[linear-gradient(180deg,rgba(56,38,7,0.38),rgba(33,21,4,0.7))]">
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-2xl border border-amber-300/80 bg-amber-100 text-amber-700 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-300">
            <ClipboardPenLine />
          </div>
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-700 dark:text-amber-300">
              Plan Approval Request
            </span>
            <p className="text-sm leading-relaxed text-foreground/90">
              子智能体已提交执行计划。您可以先改写 Markdown 计划，再决定是否批准执行。
            </p>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <span className="rounded-full border border-amber-300/70 bg-white/70 px-2 py-0.5 dark:border-amber-700/50 dark:bg-black/20">plan_id: {approval.plan_id.slice(0, 8)}</span>
              <span className="rounded-full border border-amber-300/70 bg-white/70 px-2 py-0.5 dark:border-amber-700/50 dark:bg-black/20">status: {approval.status}</span>
            </div>
          </div>
        </div>

        {approval.summary && (
          <div className="rounded-2xl border border-amber-200/80 bg-white/60 px-3 py-2 text-sm text-foreground/80 dark:border-amber-800/40 dark:bg-black/20">
            {approval.summary}
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-muted-foreground">计划 Markdown</span>
          <Textarea
            value={planContent}
            onChange={(event) => {
              setPlanContent(event.target.value)
              setParseError(null)
            }}
            disabled={isDisabled || isLoadingPlan}
            rows={Math.min(18, Math.max(8, planContent.split('\n').length + 2))}
            className="resize-y rounded-2xl border-amber-200 bg-white/75 font-mono text-xs leading-5 focus-visible:ring-amber-400 dark:border-amber-800/50 dark:bg-black/25"
            spellCheck={false}
          />
          {isLoadingPlan && <p className="text-xs text-muted-foreground">正在加载计划正文…</p>}
          {loadError && <p className="text-xs text-destructive">{loadError}</p>}
          {parseError && <p className="text-xs text-destructive">{parseError}</p>}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={isDisabled}
            className="border-amber-300 bg-transparent text-destructive hover:bg-amber-100 dark:border-amber-700/60 dark:hover:bg-amber-900/30"
            onClick={handleReject}
          >
            拒绝计划
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={isDisabled || isLoadingPlan}
            className="border-amber-300 bg-white/70 dark:border-amber-700/60 dark:bg-black/20"
            onClick={handleModify}
          >
            <FilePenLine data-icon="inline-start" />
            保存修改
          </Button>
          <Button
            size="sm"
            disabled={isDisabled || isLoadingPlan}
            className="bg-amber-500 text-white hover:bg-amber-600"
            onClick={handleApprove}
          >
            批准并执行
          </Button>
        </div>
      </div>
    )
  }

  const label = toolLabel(approval.tool_name)

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-orange-300 bg-orange-50 px-4 py-3 shadow-sm dark:border-orange-700/50 dark:bg-orange-950/20">
      <div className="flex items-start gap-2">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-orange-500" />
        <div className="flex flex-col gap-0.5">
          <span className="text-xs font-semibold text-orange-700 dark:text-orange-400">
            高耗时操作 — 需要您的授权
          </span>
          <p className="text-sm leading-relaxed text-foreground/90">
            Agent 计划执行 <span className="font-medium">{label}</span>，请确认参数后再继续。
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">调用参数（可直接编辑）</span>
        <Textarea
          value={argsJson}
          onChange={(event) => {
            setArgsJson(event.target.value)
            setParseError(null)
          }}
          disabled={isDisabled}
          rows={Math.min(12, argsJson.split('\n').length + 1)}
          className="resize-none border-orange-200 bg-white/60 font-mono text-xs focus-visible:ring-orange-400 dark:border-orange-800/40 dark:bg-black/20"
          spellCheck={false}
        />
        {parseError && <p className="text-xs text-destructive">{parseError}</p>}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={isDisabled}
          className="border-orange-300 text-destructive hover:bg-orange-100 hover:text-destructive dark:border-orange-700 dark:hover:bg-orange-900/40"
          onClick={handleReject}
        >
          拒绝执行
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={isDisabled}
          className="border-orange-300 hover:bg-orange-100 dark:border-orange-700 dark:hover:bg-orange-900/40"
          onClick={handleModify}
        >
          修改后执行
        </Button>
        <Button
          size="sm"
          disabled={isDisabled}
          className="bg-orange-500 text-white hover:bg-orange-600"
          onClick={handleApprove}
        >
          确认执行
        </Button>
      </div>
    </div>
  )
}

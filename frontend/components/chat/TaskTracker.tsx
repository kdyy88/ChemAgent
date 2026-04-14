'use client'

import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleDashed,
  Loader2,
} from 'lucide-react'
import type { SSETaskItem, TaskStatus } from '@/lib/sse-types'

interface TaskTrackerProps {
  tasks: SSETaskItem[]
  isStreaming: boolean
}

const STATUS_META: Record<
  TaskStatus,
  { label: string; dotClass: string; Icon: typeof CircleDashed; itemClass?: string }
> = {
  pending: {
    label: '待执行',
    dotClass: 'text-muted-foreground/70',
    Icon: CircleDashed,
  },
  in_progress: {
    label: '进行中',
    dotClass: 'text-sky-600 animate-spin',
    Icon: Loader2,
  },
  completed: {
    label: '已完成',
    dotClass: 'text-emerald-600',
    Icon: CheckCircle2,
    itemClass: 'line-through opacity-55',
  },
  failed: {
    label: '失败',
    dotClass: 'text-destructive',
    Icon: AlertTriangle,
  },
}

export function TaskTracker({ tasks, isStreaming }: TaskTrackerProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  const sortedTasks = useMemo(() => {
    const order: Record<TaskStatus, number> = {
      in_progress: 0,
      pending: 1,
      failed: 2,
      completed: 3,
    }

    return [...tasks].sort((left, right) => {
      const orderDiff = order[left.status] - order[right.status]
      if (orderDiff !== 0) return orderDiff
      return Number(left.id) - Number(right.id)
    })
  }, [tasks])

  if (tasks.length === 0) return null

  const completedCount = tasks.filter((task) => task.status === 'completed').length
  const failedTask = tasks.find((task) => task.status === 'failed')
  const currentTask =
    tasks.find((task) => task.status === 'in_progress') ??
    tasks.find((task) => task.status === 'pending') ??
    failedTask

  const summary = failedTask
    ? `任务异常 · ${failedTask.description}`
    : completedCount === tasks.length
      ? '任务全部完成'
      : currentTask
        ? `进度: ${completedCount}/${tasks.length} · ${currentTask.description}`
        : isStreaming
          ? `进度: ${completedCount}/${tasks.length} · 等待智能体选择下一步任务`
          : '本轮任务执行结束'

  const isDone = completedCount === tasks.length && !failedTask
  const HeaderIcon = isDone ? CheckCircle2 : Loader2
  const headerIconClass = isDone ? 'text-emerald-600' : 'text-sky-600 animate-spin'

  return (
    <div className="overflow-hidden rounded-lg border border-border/60 bg-muted/20 transition-all duration-200">
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2 overflow-hidden">
          <HeaderIcon className={`h-3 w-3 shrink-0 ${headerIconClass}`} />
          <span className="truncate text-[12px] font-medium text-foreground/80">{summary}</span>
        </div>
        <button
          type="button"
          onClick={() => setIsExpanded((expanded) => !expanded)}
          className="rounded-md w-5 h-5 flex items-center justify-center text-muted-foreground/60 transition-colors hover:bg-muted/60 hover:text-foreground"
          aria-expanded={isExpanded}
          aria-label={isExpanded ? '折叠任务详情' : '展开任务详情'}
        >
          {isExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
      </div>

      {isExpanded && (
        <div className="max-h-40 space-y-1 overflow-y-auto border-t border-border/50 bg-background/40 px-3 pb-2.5 pt-2">
          {sortedTasks.map((task) => {
          const meta = STATUS_META[task.status]
          const Icon = meta.Icon
          return (
            <div
              key={task.id}
              className="flex items-center gap-2"
            >
              <Icon className={`h-3 w-3 shrink-0 ${meta.dotClass}`} />
              <span className="text-[10px] font-mono text-muted-foreground/50">
                {task.id}.
              </span>
              <span className={`min-w-0 truncate text-[11px] text-muted-foreground/70 ${meta.itemClass ?? ''}`}>{task.description}</span>
              <span className="ml-auto shrink-0 text-[10px] uppercase tracking-[0.08em] text-muted-foreground/50">
                {meta.label}
              </span>
            </div>
          )
          })}
        </div>
      )}
    </div>
  )
}
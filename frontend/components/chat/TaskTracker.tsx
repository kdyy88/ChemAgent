'use client'

import { AlertTriangle, CheckCircle2, Circle, ListTodo, LoaderCircle } from 'lucide-react'
import type { SSETaskItem, TaskStatus } from '@/lib/sse-types'

interface TaskTrackerProps {
  tasks: SSETaskItem[]
  isStreaming: boolean
}

const STATUS_META: Record<TaskStatus, { label: string; dotClass: string; Icon: typeof Circle }> = {
  pending: {
    label: '待执行',
    dotClass: 'text-muted-foreground/70',
    Icon: Circle,
  },
  in_progress: {
    label: '进行中',
    dotClass: 'text-sky-600 animate-spin',
    Icon: LoaderCircle,
  },
  completed: {
    label: '已完成',
    dotClass: 'text-emerald-600',
    Icon: CheckCircle2,
  },
  failed: {
    label: '失败',
    dotClass: 'text-destructive',
    Icon: AlertTriangle,
  },
}

export function TaskTracker({ tasks, isStreaming }: TaskTrackerProps) {
  const completedCount = tasks.filter((task) => task.status === 'completed').length
  const activeTask = tasks.find((task) => task.status === 'in_progress')
  const summary = activeTask
    ? `执行中: ${activeTask.description}`
    : isStreaming
      ? '等待智能体选择下一步任务'
      : '本轮任务执行结束'

  return (
    <div className="rounded-2xl border bg-muted/30 p-3 shadow-sm">
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary">
          <ListTodo className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold tracking-tight">任务清单</div>
          <div className="text-xs text-muted-foreground">
            {completedCount}/{tasks.length} 已完成 · {summary}
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-col gap-2">
        {tasks.map((task) => {
          const meta = STATUS_META[task.status]
          const Icon = meta.Icon
          return (
            <div
              key={task.id}
              className="flex items-start gap-2 rounded-xl border bg-background/90 px-3 py-2"
            >
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${meta.dotClass}`} />
              <div className="min-w-0 flex-1">
                <div className="text-sm leading-5 text-foreground">
                  <span className="mr-1 text-muted-foreground">{task.id}.</span>
                  {task.description}
                </div>
                <div className="mt-0.5 text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
                  {meta.label}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
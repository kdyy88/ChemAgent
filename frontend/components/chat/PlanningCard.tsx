'use client'

import { motion, AnimatePresence } from 'framer-motion'
import { ClipboardList, CircleDashed } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import type { SSETaskItem } from '@/lib/sse-types'

interface PlanningCardProps {
  tasks: SSETaskItem[]
  isGenerating: boolean // true when planner_node is active but tasks haven't arrived
  isStreaming: boolean
}

export function PlanningCard({ tasks, isGenerating, isStreaming }: PlanningCardProps) {
  const showSkeleton = isGenerating && tasks.length === 0
  const showTasks = tasks.length > 0

  if (!showSkeleton && !showTasks) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="rounded-xl border border-primary/20 bg-primary/5 overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-primary/15 bg-primary/8">
        <ClipboardList className="h-3.5 w-3.5 text-primary/70 shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-primary/80 tracking-tight">
          {showSkeleton ? '正在制定执行计划…' : `执行计划 · ${tasks.length} 个步骤`}
        </span>
        {isStreaming && showSkeleton && (
          <span className="ml-auto flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="inline-block w-1 h-1 rounded-full bg-primary/50 animate-bounce"
                style={{ animationDelay: `${i * 120}ms` }}
                aria-hidden="true"
              />
            ))}
          </span>
        )}
      </div>

      {/* Body */}
      <div className="px-3 py-2.5 space-y-2">
        <AnimatePresence mode="popLayout">
          {showSkeleton ? (
            // Skeleton rows — 3 lines hinting at tasks to come
            <motion.div key="skeletons" className="space-y-2" exit={{ opacity: 0 }}>
              {[80, 65, 72].map((w, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Skeleton className="h-3 w-3 rounded-full shrink-0" />
                  <Skeleton className="h-3 rounded-md" style={{ width: `${w}%` }} />
                </div>
              ))}
            </motion.div>
          ) : (
            // Real task items — staggered fade-in
            tasks.map((task, i) => (
              <motion.div
                key={task.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.2, delay: i * 0.06, ease: 'easeOut' }}
                className="flex items-center gap-2 text-xs text-foreground/75"
              >
                <CircleDashed className="h-3 w-3 shrink-0 text-primary/40" aria-hidden="true" />
                <span className="tabular-nums text-[10px] text-muted-foreground/60 font-mono shrink-0">
                  {String(task.id).padStart(2, '0')}
                </span>
                <span className="truncate">{task.description}</span>
              </motion.div>
            ))
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}

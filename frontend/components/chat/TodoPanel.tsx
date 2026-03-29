'use client'

import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, CheckCircle2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { TodoChecklist, parseTodoLines } from './TodoChecklist'
import { useChemAgent } from '@/hooks/useChemAgent'

export function TodoPanel() {
  const { turns } = useChemAgent()
  const [open, setOpen] = useState(false)

  // Find latest todo from the most recent active or recently-done turn
  const activeTurn = [...turns]
    .reverse()
    .find((t) => t.status === 'thinking' || t.status === 'awaiting_approval' || t.status === 'done')

  const todoSteps = activeTurn?.steps.filter((s) => s.kind === 'todo') ?? []
  const lastTodo = todoSteps.length > 0 ? todoSteps[todoSteps.length - 1] : null
  const todoText = lastTodo?.kind === 'todo' ? lastTodo.todo : null

  // Track previous todoText to auto-expand when new frames arrive
  const prevTodoRef = useRef<string | null>(null)
  useEffect(() => {
    if (todoText && todoText !== prevTodoRef.current) {
      setOpen(true)
      prevTodoRef.current = todoText
    }
  }, [todoText])

  // Auto-collapse when turn is done
  useEffect(() => {
    if (activeTurn?.status === 'done') {
      const timer = setTimeout(() => setOpen(false), 1500)
      return () => clearTimeout(timer)
    }
  }, [activeTurn?.status])

  if (!todoText) return null

  const { items, hasCheckboxes } = parseTodoLines(todoText)
  const checkedCount = hasCheckboxes ? items.filter((i) => i.checked).length : 0
  const total = hasCheckboxes ? items.length : 0

  // Extract a meaningful title from the active turn's user message
  const taskTitle = activeTurn?.userMessage?.slice(0, 28) || '当前任务'

  return (
    <div className="border-t bg-card/60 backdrop-blur supports-[backdrop-filter]:bg-card/50 shadow-sm">
      {/* Header / toggle row */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex w-full items-center gap-2 px-3 py-2 text-left',
          'hover:bg-muted/50 transition-colors',
        )}
      >
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-500" />
        <span className="flex-1 truncate text-[11px] font-medium text-muted-foreground">
          🚀 {taskTitle}
        </span>
        {hasCheckboxes && total > 0 && (
          <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
            {checkedCount}/{total}
          </span>
        )}
        {open ? (
          <ChevronUp className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
      </button>

      {/* Expandable body */}
      <div
        className={cn(
          'overflow-hidden transition-all duration-200',
          open ? 'max-h-64 opacity-100' : 'max-h-0 opacity-0',
        )}
      >
        <div className="overflow-y-auto max-h-60 px-4 pb-3 pt-1">
          <TodoChecklist todo={todoText} />
        </div>
      </div>
    </div>
  )
}

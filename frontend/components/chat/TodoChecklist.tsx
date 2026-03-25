'use client'

import { memo, useRef, useEffect, useState } from 'react'
import { CheckSquare, Square } from 'lucide-react'
import { cn } from '@/lib/utils'

interface TodoChecklistProps {
  todo: string
}

/** Regex to match `- [ ] text` or `- [x] text` lines. */
const CHECKBOX_RE = /^-\s*\[([ xX])\]\s*(.+)$/

type TodoItem = { checked: boolean; label: string }

export function parseTodoLines(text: string): { items: TodoItem[]; hasCheckboxes: boolean } {
  const lines = text.split('\n')
  const items: TodoItem[] = []
  let hasCheckboxes = false

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue

    const match = CHECKBOX_RE.exec(trimmed)
    if (match) {
      hasCheckboxes = true
      items.push({ checked: match[1].toLowerCase() === 'x', label: match[2] })
    } else {
      // Non-checkbox line — keep as unchecked plain text
      items.push({ checked: false, label: trimmed })
    }
  }
  return { items, hasCheckboxes }
}

export const TodoChecklist = memo(function TodoChecklist({ todo }: TodoChecklistProps) {
  const { items, hasCheckboxes } = parseTodoLines(todo)

  // Track which indices were previously checked to detect transitions
  const prevChecked = useRef<Set<number>>(new Set())
  const [justChecked, setJustChecked] = useState<Set<number>>(new Set())

  useEffect(() => {
    const newlyChecked = new Set<number>()
    items.forEach((item, i) => {
      if (item.checked && !prevChecked.current.has(i)) {
        newlyChecked.add(i)
      }
    })

    if (newlyChecked.size > 0) {
      setJustChecked(newlyChecked)
      // Clear animation class after it completes
      const timer = setTimeout(() => setJustChecked(new Set()), 600)

      // Update ref for next render
      prevChecked.current = new Set(
        items.map((item, i) => (item.checked ? i : -1)).filter((i) => i >= 0),
      )
      return () => clearTimeout(timer)
    }

    // Update ref for next render
    prevChecked.current = new Set(
      items.map((item, i) => (item.checked ? i : -1)).filter((i) => i >= 0),
    )
  }, [items])

  // Fallback: if no checkbox syntax detected, render raw text as before
  if (!hasCheckboxes || items.length === 0) {
    return (
      <p className="font-mono text-[11px] whitespace-pre-wrap break-all">
        {todo}
      </p>
    )
  }

  return (
    <ul className="flex flex-col gap-0.5">
      {items.map((item, i) => {
        const isNewlyChecked = justChecked.has(i)
        return (
          <li
            key={i}
            className={cn(
              'flex items-start gap-1.5 text-[11px] leading-relaxed rounded-sm px-0.5',
              'transition-all duration-300',
              item.checked && 'text-muted-foreground',
              isNewlyChecked && 'animate-todo-flash',
            )}
          >
            {item.checked ? (
              <CheckSquare
                className={cn(
                  'h-3.5 w-3.5 shrink-0 mt-0.5 text-green-500',
                  isNewlyChecked && 'animate-todo-check',
                )}
              />
            ) : (
              <Square className="h-3.5 w-3.5 shrink-0 mt-0.5 text-muted-foreground" />
            )}
            <span className={cn(
              'transition-all duration-300',
              item.checked && 'line-through',
            )}>
              {item.label}
            </span>
          </li>
        )
      })}
    </ul>
  )
})

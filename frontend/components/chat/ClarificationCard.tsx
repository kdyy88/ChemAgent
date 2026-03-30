'use client'

/**
 * ClarificationCard — Human-in-the-Loop UI
 *
 * Rendered when LangGraph pauses on a native interrupt and requests
 * clarification.  Displays the question, quick-reply option buttons, and a
 * free-text input.  On submission it calls useSseStore.sendMessage() with the
 * interrupt id so the backend can resume from the persisted checkpoint.
 */

import { useState, useRef, useEffect } from 'react'
import { HelpCircle, ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useSseStore, type InterruptContext } from '@/store/sseStore'

interface ClarificationCardProps {
  interrupt: {
    question: string
    options: string[]
    called_tools: string[]
    interrupt_id: string
    known_smiles?: string
  }
  /** The original user message that triggered the research (for context). */
  researchTopic: string
}

export function ClarificationCard({ interrupt, researchTopic }: ClarificationCardProps) {
  const [customText, setCustomText] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const { sendMessage, isStreaming } = useSseStore()

  // Auto-focus the text input when the card appears
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const isDisabled = isStreaming || submitted

  async function handleSend(answer: string) {
    if (!answer.trim() || isDisabled) return
    setSubmitted(true)

    const interruptContext: InterruptContext = {
      interrupt_id: interrupt.interrupt_id,
    }

    // The backend submits this as Command(resume=...) against the pending interrupt.
    const message = answer.trim()

    await sendMessage(message, { interruptContext })
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend(customText)
    }
  }

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 dark:border-amber-800/50 dark:bg-amber-950/30 px-4 py-3 flex flex-col gap-3 shadow-sm">
      {/* Header */}
      <div className="flex items-start gap-2">
        <HelpCircle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
        <div className="flex flex-col gap-0.5">
          <span className="text-xs font-semibold text-amber-700 dark:text-amber-400">
            需要您的确认
          </span>
          <p className="text-sm text-foreground/90 leading-relaxed">{interrupt.question}</p>
        </div>
      </div>

      {/* Quick-reply option buttons */}
      {interrupt.options.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {interrupt.options.map((opt, i) => (
            <Button
              key={i}
              variant="outline"
              size="sm"
              disabled={isDisabled}
              className="h-7 text-xs border-amber-300 hover:bg-amber-100 dark:border-amber-700 dark:hover:bg-amber-900/40"
              onClick={() => handleSend(opt)}
            >
              {opt}
            </Button>
          ))}
        </div>
      )}

      {/* Free-text input */}
      <div className="flex items-center gap-2">
        <Input
          ref={inputRef}
          value={customText}
          onChange={(e) => setCustomText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isDisabled}
          placeholder="或输入您的回答…"
          className="h-8 text-sm flex-1 bg-white dark:bg-background border-amber-300 dark:border-amber-700 focus-visible:ring-amber-400"
        />
        <Button
          size="sm"
          disabled={!customText.trim() || isDisabled}
          className="h-8 w-8 p-0 bg-amber-500 hover:bg-amber-600 text-white shrink-0"
          onClick={() => handleSend(customText)}
        >
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </div>

      {submitted && (
        <p className="text-xs text-muted-foreground">已发送，研究将从此处继续…</p>
      )}
    </div>
  )
}

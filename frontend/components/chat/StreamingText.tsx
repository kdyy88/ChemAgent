'use client'

import { memo, useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

/**
 * StreamingText — renders incrementally-arriving text with a smooth
 * fade-in effect on newly appended characters.
 *
 * Unlike `<ResponseStream>` (which animates a complete string), this
 * component is designed for the chat streaming use case where `text`
 * grows on each state update (appended chunks from WebSocket).
 *
 * Strategy:
 * - Track the "committed" length (already displayed without animation).
 * - On each render, the stable prefix renders instantly; the new tail
 *   fades in via a CSS animation.
 * - After the animation completes (or a short timeout), the committed
 *   length advances so the tail becomes part of the stable prefix.
 */
interface StreamingTextProps {
  /** The current accumulated text (grows with each chunk). */
  text: string
  className?: string
}

export const StreamingText = memo(function StreamingText({
  text,
  className,
}: StreamingTextProps) {
  // How many characters have already been "committed" (shown without animation)
  const [committed, setCommitted] = useState(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const stableText = text.slice(0, committed)
  const newText = text.slice(committed)

  // Commit the new text after a brief delay so the fade has time to play
  useEffect(() => {
    if (newText.length === 0) return

    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      setCommitted(text.length)
    }, 300)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [text.length, newText.length])

  // Reset committed when text is cleared (new turn)
  useEffect(() => {
    if (text.length === 0) setCommitted(0)
  }, [text.length])

  return (
    <span className={cn('whitespace-pre-wrap', className)}>
      {stableText}
      {newText && (
        <span className="animate-fade-in">{newText}</span>
      )}
    </span>
  )
})

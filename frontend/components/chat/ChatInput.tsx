'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Loader2, Send } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useChemAgent } from '@/hooks/useChemAgent'

export function ChatInput() {
  const [value, setValue] = useState('')
  const { isStreaming, sendMessage } = useChemAgent()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || isStreaming) return
    sendMessage(trimmed)
    setValue('')
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2 w-full">
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Ask about any chemical compound…"
        disabled={isStreaming}
        className="flex-1"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSubmit(e as unknown as React.FormEvent)
          }
        }}
      />

      <AnimatePresence mode="wait">
        {isStreaming ? (
          <motion.div
            key="analyzing"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
          >
            <Badge
              variant="secondary"
              className="flex items-center gap-1.5 px-3 py-2 h-9 text-sm"
            >
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Analyzing…
            </Badge>
          </motion.div>
        ) : (
          <motion.div
            key="send"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
          >
            <Button type="submit" disabled={!value.trim()} size="default">
              <Send className="h-4 w-4" />
              Send
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </form>
  )
}

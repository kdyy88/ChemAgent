'use client'

import { useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { FlaskConical } from 'lucide-react'
import { AnimatePresence } from 'framer-motion'
import { ScrollArea } from '@/components/ui/scroll-area'
import { MessageBubble } from './MessageBubble'
import { useChemAgent } from '@/hooks/useChemAgent'

export function MessageList() {
  const { turns, isStreaming, toolCatalog } = useChemAgent()
  const bottomRef = useRef<HTMLDivElement>(null)
  const lastTurn = turns[turns.length - 1]
  const lastStepCount = lastTurn?.steps.length ?? 0
  const lastArtifactCount = lastTurn?.artifacts.length ?? 0

  // Auto-scroll when new steps arrive or a new turn appears
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns.length, lastStepCount, lastArtifactCount, isStreaming])

  return (
    <ScrollArea className="h-full">
      <div className="max-w-5xl mx-auto px-4 py-6 flex flex-col gap-6">
        {turns.length === 0 ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.2, duration: 0.4 }}
            className="flex flex-col items-center justify-center gap-4 py-24 text-center"
          >
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted">
              <FlaskConical className="h-8 w-8 text-muted-foreground" />
            </div>
            <div className="space-y-1">
              <p className="text-base font-medium text-foreground">
                Ask me about any chemical compound
              </p>
              <p className="text-sm text-muted-foreground">
                Try entering a name like &ldquo;Aspirin&rdquo; or &ldquo;扑热息痛&rdquo;
              </p>
            </div>
          </motion.div>
        ) : (
          <AnimatePresence initial={false}>
            {turns.map((turn) => (
              <MessageBubble key={turn.id} turn={turn} toolCatalog={toolCatalog} />
            ))}
          </AnimatePresence>
        )}

        {/* Scroll sentinel */}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  )
}

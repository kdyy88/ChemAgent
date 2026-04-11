'use client'

import { Bot, Trash2 } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { useSSEChemAgent } from '@/hooks/useSSEChemAgent'
import { Button } from '@/components/ui/button'
import { SSEMessageList } from '@/components/chat/SSEMessageList'
import { SSEChatInput } from '@/components/chat/SSEChatInput'
import { TaskTracker } from '@/components/chat/TaskTracker'

export function AgentChatPanel() {
  const { turns, isStreaming, sendMessage, clearTurns } = useSSEChemAgent()
  const latestTasks = turns.at(-1)?.tasks ?? []

  return (
    <div className="relative flex h-full flex-col overflow-hidden bg-background/50">
      {/* ── Header ── */}
      <div className="shrink-0 flex items-center gap-2 px-3 py-2.5 border-b bg-background/90 backdrop-blur">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/15">
          <Bot className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
        </div>
        <span className="text-sm font-semibold tracking-tight">Agent</span>

        <div className="ml-auto flex items-center gap-1.5">
          {turns.length > 0 && (
            <span className="text-xs text-muted-foreground tabular-nums">
              {turns.length} turn{turns.length !== 1 ? 's' : ''}
            </span>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
            onClick={clearTurns}
            disabled={isStreaming || turns.length === 0}
            title="Clear history"
            aria-label="Clear conversation history"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {/* ── Message area ── */}
      <div className="min-h-0 flex-1 overflow-hidden">
        <SSEMessageList turns={turns} />
      </div>

      {/* ── Footer: task tracker + input ── */}
      <div className="shrink-0 border-t bg-background/95 backdrop-blur">
        <AnimatePresence initial={false}>
          {latestTasks.length > 0 && (
            <motion.div
              key="task-tracker"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25, ease: 'easeOut' }}
              className="overflow-hidden px-4 pt-3"
            >
              <TaskTracker tasks={latestTasks} isStreaming={isStreaming} />
            </motion.div>
          )}
        </AnimatePresence>

        <div className="p-4 pt-3">
          <SSEChatInput
            isStreaming={isStreaming}
            sendMessage={sendMessage}
          />
        </div>
      </div>
    </div>
  )
}

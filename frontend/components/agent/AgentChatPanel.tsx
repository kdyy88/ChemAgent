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
    <div className="relative flex h-full flex-col overflow-hidden bg-background">
      {/* ── Header ── */}
      <div className="shrink-0 flex items-center gap-2.5 px-4 h-11 border-b border-border/70 bg-background/90 backdrop-blur-sm">
        <div className="flex h-5.5 w-5.5 items-center justify-center rounded-md bg-primary/12 border border-primary/20">
          <Bot className="h-3 w-3 text-primary" aria-hidden="true" />
        </div>
        <span className="text-[13px] font-semibold tracking-[-0.01em] text-foreground">Agent</span>
        <span className="text-[11px] text-muted-foreground/50 tracking-[0.06em] uppercase font-medium hidden sm:inline">Chat</span>

        <div className="ml-auto flex items-center gap-2">
          {turns.length > 0 && (
            <span className="text-[11px] text-muted-foreground/60 tabular-nums font-medium">
              {turns.length} turn{turns.length !== 1 ? 's' : ''}
            </span>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0 text-muted-foreground/50 hover:text-destructive hover:bg-destructive/8 transition-colors"
            onClick={clearTurns}
            disabled={isStreaming || turns.length === 0}
            title="Clear history"
            aria-label="Clear conversation history"
          >
            <Trash2 className="h-3 w-3" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {/* ── Message area ── */}
      <div className="min-h-0 flex-1 overflow-hidden">
        <SSEMessageList turns={turns} />
      </div>

      {/* ── Footer: task tracker + input ── */}
      <div className="shrink-0 border-t border-border/70 bg-background/95 backdrop-blur-sm">
        <AnimatePresence initial={false}>
          {latestTasks.length > 0 && (
            <motion.div
              key="task-tracker"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
              className="overflow-hidden px-4 pt-3"
            >
              <TaskTracker tasks={latestTasks} isStreaming={isStreaming} />
            </motion.div>
          )}
        </AnimatePresence>

        <div className="p-3">
          <SSEChatInput
            isStreaming={isStreaming}
            sendMessage={sendMessage}
          />
        </div>
      </div>
    </div>
  )
}

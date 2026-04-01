'use client'

import { AnimatePresence, motion } from 'framer-motion'
import { FlaskConical, Trash2 } from 'lucide-react'
import { useSSEChemAgent } from '@/hooks/useSSEChemAgent'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SSEMessageList } from './SSEMessageList'
import { SSEChatInput } from './SSEChatInput'
import { TaskTracker } from './TaskTracker'

export function CopilotSidebar() {
  const { turns, isStreaming, sendMessage, clearTurns } = useSSEChemAgent()
  const { currentSmiles, currentName } = useWorkspaceStore()
  const latestTasks = turns.at(-1)?.tasks ?? []

  const hasSmiles = Boolean(currentSmiles)
  const smilesLabel = currentName || (currentSmiles ? currentSmiles.slice(0, 22) + (currentSmiles.length > 22 ? '…' : '') : '')

  return (
    <div className="relative flex h-full flex-col border-l bg-muted/10 shadow-inner">
      {/* ── Header ── */}
      <div className="shrink-0 flex items-center gap-2 px-3 py-2 border-b bg-background/80 backdrop-blur">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10">
          <FlaskConical className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
        </div>
        <span className="text-sm font-semibold tracking-tight">ChemAgent</span>

        <div className="ml-auto flex items-center gap-1.5">
          {/* Turn counter */}
          {turns.length > 0 && (
            <span className="text-xs text-muted-foreground tabular-nums">
              {turns.length} 轮
            </span>
          )}
          {/* Clear button */}
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
            onClick={clearTurns}
            disabled={isStreaming || turns.length === 0}
            title="清除对话记录"
            aria-label="清除对话记录"
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
      <div className="shrink-0 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
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
            clearTurns={clearTurns}
          />
        </div>
      </div>
    </div>
  )
}

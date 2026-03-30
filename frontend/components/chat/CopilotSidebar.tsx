'use client'

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
    <div className="flex flex-col h-full bg-muted/10 border-l relative shadow-inner">
      {/* ── Header ── */}
      <div className="shrink-0 flex items-center gap-2 px-3 py-2 border-b bg-background/80 backdrop-blur">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10">
          <FlaskConical className="h-3.5 w-3.5 text-primary" />
        </div>
        <span className="text-sm font-semibold tracking-tight">ChemAgent</span>

        {/* Active molecule pill */}
        {hasSmiles && (
          <Badge
            variant="outline"
            className="ml-1 max-w-[9rem] truncate text-xs font-mono bg-primary/5 border-primary/30 text-primary"
            title={currentSmiles}
          >
            🧪 {smilesLabel}
          </Badge>
        )}

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
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {latestTasks.length > 0 && (
        <div className="shrink-0 border-b bg-background/70 px-3 py-3">
          <TaskTracker tasks={latestTasks} isStreaming={isStreaming} />
        </div>
      )}

      {/* ── Message area ── */}
      <div className="flex-1 overflow-hidden">
        <SSEMessageList turns={turns} />
      </div>

      {/* ── Input ── */}
      <div className="shrink-0 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 p-4">
        <SSEChatInput
          isStreaming={isStreaming}
          sendMessage={sendMessage}
          clearTurns={clearTurns}
        />
      </div>
    </div>
  )
}

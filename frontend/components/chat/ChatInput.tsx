'use client'

import { useState, useEffect } from 'react'
import { Send, CheckCircle2, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Loader } from '@/components/ui/loader'
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputActions,
  PromptInputAction,
} from '@/components/ui/prompt-input'
import { useChemAgent } from '@/hooks/useChemAgent'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { CompactTodoStep } from './ThinkingLog'

export function ChatInput() {
  const [value, setValue] = useState('')
  // Local flag to hide buttons immediately on click (before WS state arrives)
  const [hitlDismissed, setHitlDismissed] = useState(false)
  const { turns, isStreaming, sendMessage, approvePlan, rejectPlan } = useChemAgent()
  const { currentSmiles, activeFunctionId } = useWorkspaceStore()

  // Find the currently active turn for HITL state and todo rendering
  const activeTurn = [...turns].reverse().find(
    (t) => t.status === 'thinking' || t.status === 'awaiting_approval',
  )
  const isAwaitingApproval = activeTurn?.status === 'awaiting_approval'

  // Reset the dismissed flag whenever a new awaiting_approval state appears
  useEffect(() => {
    if (isAwaitingApproval) setHitlDismissed(false)
  }, [isAwaitingApproval])

  // Show HITL buttons only when server says awaiting AND user hasn't clicked yet
  const showHitl = isAwaitingApproval && !hitlDismissed

  // Last todo step from the active turn (for progress display above input)
  const todoSteps = activeTurn?.steps.filter((s) => s.kind === 'todo') ?? []
  const lastTodo = todoSteps.length > 0 ? todoSteps[todoSteps.length - 1] : null
  const todoText = lastTodo?.kind === 'todo' ? lastTodo.todo : null

  const handleApprove = () => {
    setHitlDismissed(true)
    approvePlan()
  }

  const handleReject = () => {
    setHitlDismissed(true)
    rejectPlan()
  }

  const handleSubmit = () => {
    const trimmed = value.trim()
    if (!trimmed || isStreaming) return

    // Inject context implicitly
    const payloadContext = currentSmiles
      ? `\n\n[系统附加信息：用户当前正在 ${activeFunctionId} 功能面操作分子：${currentSmiles}]`
      : ''

    sendMessage(trimmed + payloadContext)
    setValue('')
  }

  return (
    <div className="flex flex-col gap-1.5">
      {/* Todo progress — above input box (Claude/Cursor style) */}
      {todoText && (
        <div className="rounded-xl border bg-card/60 px-3 py-2 shadow-sm">
          <CompactTodoStep todo={todoText} />
        </div>
      )}

      {/* HITL approve / reject — above the input, disappears immediately on click */}
      {showHitl && (
        <div className="flex items-center justify-end gap-2 px-1">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 px-2.5 text-xs text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700"
            onClick={handleReject}
          >
            <XCircle className="h-3.5 w-3.5 mr-1" />
            拒绝
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-7 px-3 text-xs"
            onClick={handleApprove}
          >
            <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
            立即执行
          </Button>
        </div>
      )}

      <PromptInput
        value={value}
        onValueChange={setValue}
        isLoading={isStreaming}
        onSubmit={handleSubmit}
        disabled={isStreaming}
        className="w-full"
      >
        <PromptInputTextarea placeholder="Ask about any chemical compound…" />
        <PromptInputActions className="justify-end">
          {isStreaming ? (
            <div className="flex items-center gap-1.5 px-3 text-sm text-muted-foreground">
              <Loader variant="typing" size="sm" />
              <span>Analyzing…</span>
            </div>
          ) : (
            <PromptInputAction tooltip="Send message">
              <Button
                type="button"
                size="default"
                disabled={!value.trim()}
                onClick={handleSubmit}
              >
                <Send className="h-4 w-4" />
                Send
              </Button>
            </PromptInputAction>
          )}
        </PromptInputActions>
      </PromptInput>
    </div>
  )
}

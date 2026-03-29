'use client'

import { useState, useEffect } from 'react'
import { Send, CheckCircle2, Pencil, FlaskConical } from 'lucide-react'
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
import { cn } from '@/lib/utils'

export function ChatInput() {
  const [value, setValue] = useState('')
  // Local flag to hide buttons immediately on click (before WS state arrives)
  const [hitlDismissed, setHitlDismissed] = useState(false)
  // When user clicks "我要修改", reactivate textarea for refinement input
  const [editMode, setEditMode] = useState(false)
  const { turns, isStreaming, sendMessage, approvePlan, rejectPlan } = useChemAgent()
  const { currentSmiles, activeFunctionId } = useWorkspaceStore()

  // Find the currently active turn for HITL state
  const activeTurn = [...turns].reverse().find(
    (t) => t.status === 'thinking' || t.status === 'awaiting_approval',
  )
  const isAwaitingApproval = activeTurn?.status === 'awaiting_approval'

  // Reset dismissed/edit flags whenever a new awaiting_approval state appears
  useEffect(() => {
    if (isAwaitingApproval) {
      setHitlDismissed(false)
      setEditMode(false)
      setValue('')
    }
  }, [isAwaitingApproval])

  // Show HITL overlay only when server says awaiting AND user hasn't clicked yet
  const showHitl = isAwaitingApproval && !hitlDismissed

  const handleApprove = () => {
    setHitlDismissed(true)
    setEditMode(false)
    approvePlan()
  }

  const handleEdit = () => {
    setEditMode(true)
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
    setEditMode(false)
    setHitlDismissed(true)
  }

  // Whether the textarea should be locked (locked while HITL is showing and NOT in edit mode)
  const inputLocked = showHitl && !editMode

  return (
    <div className="flex flex-col gap-2">

      {/* ── HITL Interruptive Input Area ─────────────────────────────────── */}
      {showHitl && !editMode && (
        <div className="rounded-2xl border-2 border-primary/30 bg-primary/5 p-3 flex flex-col gap-2 shadow-sm">
          <div className="flex items-center gap-1.5 text-xs font-medium text-primary">
            <FlaskConical className="h-3.5 w-3.5 shrink-0" />
            <span>ChemAgent 已制定执行计划，等待您的确认</span>
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              className="flex-1 h-9 text-sm font-semibold shadow-sm"
              onClick={handleApprove}
            >
              <CheckCircle2 className="h-4 w-4 mr-1.5" />
              批准计划，开始执行
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-9 text-sm px-3"
              onClick={handleEdit}
            >
              <Pencil className="h-3.5 w-3.5 mr-1" />
              我要修改
            </Button>
          </div>
        </div>
      )}

      {/* ── Main prompt input ─────────────────────────────────────────────── */}
      <PromptInput
        value={value}
        onValueChange={setValue}
        isLoading={isStreaming}
        onSubmit={handleSubmit}
        disabled={isStreaming || inputLocked}
        className={cn('w-full transition-opacity', inputLocked && 'opacity-40 pointer-events-none')}
      >
        <PromptInputTextarea
          placeholder={
            editMode
              ? '请告诉 ChemAgent 您想补充或修改什么，例如：请额外补充毒性预测...'
              : 'Ask about any chemical compound…'
          }
        />
        <PromptInputActions className="justify-end">
          {isStreaming ? (
            <div className="flex items-center gap-1.5 px-3 text-sm text-muted-foreground">
              <Loader variant="typing" size="sm" />
              <span>Analyzing…</span>
            </div>
          ) : (
            <PromptInputAction tooltip={editMode ? '发送修改意见' : 'Send message'}>
              <Button
                type="button"
                size="default"
                disabled={!value.trim()}
                onClick={handleSubmit}
              >
                <Send className="h-4 w-4" />
                {editMode ? '发送' : 'Send'}
              </Button>
            </PromptInputAction>
          )}
        </PromptInputActions>
      </PromptInput>
    </div>
  )
}

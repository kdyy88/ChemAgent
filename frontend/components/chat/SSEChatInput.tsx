'use client'

import { useState } from 'react'
import { Send, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Loader } from '@/components/ui/loader'
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputActions,
  PromptInputAction,
} from '@/components/ui/prompt-input'
import { useWorkspaceStore } from '@/store/workspaceStore'

interface SSEChatInputProps {
  isStreaming: boolean
  sendMessage: (message: string, options?: { activeSmiles?: string | null }) => Promise<void>
  clearTurns: () => void
}

export function SSEChatInput({ isStreaming, sendMessage, clearTurns }: SSEChatInputProps) {
  const [value, setValue] = useState('')
  const { currentSmiles, activeFunctionId } = useWorkspaceStore()

  const handleSubmit = async () => {
    const trimmed = value.trim()
    if (!trimmed || isStreaming) return
    setValue('')
    await sendMessage(trimmed, { activeSmiles: currentSmiles ?? null })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <PromptInput
      value={value}
      onValueChange={setValue}
      isLoading={isStreaming}
      onSubmit={handleSubmit}
      disabled={isStreaming}
      className="w-full"
    >
      <PromptInputTextarea
        placeholder={
          activeFunctionId && currentSmiles
            ? `问关于 ${currentSmiles.slice(0, 20)}… 的问题`
            : 'Ask about any chemical compound…'
        }
        onKeyDown={handleKeyDown}
      />
      <PromptInputActions className="justify-between">
        {/* Clear history */}
        <PromptInputAction tooltip="清除对话记录">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            onClick={clearTurns}
            disabled={isStreaming}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </PromptInputAction>

        {/* Send / streaming indicator */}
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
  )
}

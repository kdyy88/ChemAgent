'use client'

import { useState } from 'react'
import { Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Loader } from '@/components/ui/loader'
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputActions,
  PromptInputAction,
} from '@/components/ui/prompt-input'
import { useChemAgent } from '@/hooks/useChemAgent'

export function ChatInput() {
  const [value, setValue] = useState('')
  const { isStreaming, sendMessage } = useChemAgent()

  const handleSubmit = () => {
    const trimmed = value.trim()
    if (!trimmed || isStreaming) return
    sendMessage(trimmed)
    setValue('')
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
  )
}

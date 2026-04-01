'use client'

import { useState } from 'react'
import { Send, X, Plus, Upload, Globe } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Loader } from '@/components/ui/loader'
import { Badge } from '@/components/ui/badge'
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputActions,
  PromptInputAction,
} from '@/components/ui/prompt-input'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useWorkspaceStore } from '@/store/workspaceStore'

interface SSEChatInputProps {
  isStreaming: boolean
  sendMessage: (message: string, options?: { activeSmiles?: string | null }) => Promise<void>
  clearTurns: () => void
}

export function SSEChatInput({ isStreaming, sendMessage, clearTurns }: SSEChatInputProps) {
  const [value, setValue] = useState('')
  const [chatSmiles, setChatSmiles] = useState<string | null>(null)
  const { currentSmiles, activeFunctionId } = useWorkspaceStore()

  const handleSubmit = async () => {
    const trimmed = value.trim()
    if (!trimmed || isStreaming) return
    setValue('')
    await sendMessage(trimmed, { activeSmiles: chatSmiles ?? null })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleAddSmiles = () => {
    if (currentSmiles && !chatSmiles) {
      setChatSmiles(currentSmiles)
    }
  }

  const handleRemoveSmiles = () => {
    setChatSmiles(null)
  }

  const smilesLabel = chatSmiles ? chatSmiles.slice(0, 22) + (chatSmiles.length > 22 ? '…' : '') : ''

  return (
    <PromptInput
      value={value}
      onValueChange={setValue}
      isLoading={isStreaming}
      onSubmit={handleSubmit}
      disabled={isStreaming}
      className="w-full"
    >
      {/* SMILES Tag Section */}
      {chatSmiles && (
        <div className="flex items-center gap-2 px-2 pt-2 pb-1">
          <Badge
            variant="outline"
            className="text-xs font-mono bg-primary/5 border-primary/30 text-primary"
            title={chatSmiles}
          >
            🧪 {smilesLabel}
            <button
              onClick={handleRemoveSmiles}
              disabled={isStreaming}
              className="ml-1 inline-flex items-center justify-center rounded-full hover:bg-primary/20 disabled:opacity-50"
              aria-label="Remove SMILES"
            >
              <X className="h-3 w-3" />
            </button>
          </Badge>
        </div>
      )}

      <PromptInputTextarea
        placeholder={
          activeFunctionId && currentSmiles
            ? `问关于 ${currentSmiles.slice(0, 20)}… 的问题`
            : 'Ask about any chemical compound…'
        }
        onKeyDown={handleKeyDown}
      />
      <PromptInputActions className="justify-between">
        {/* Add SMILES Dropdown Menu */}
        <PromptInputAction tooltip="添加数据源到聊天框">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 px-2"
                disabled={isStreaming}
                aria-label="Add data source"
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top" className="w-48">
              <DropdownMenuItem
                onClick={handleAddSmiles}
                disabled={!currentSmiles || !!chatSmiles || isStreaming}
              >
                <span>添加当前 SMILES</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled>
                <Upload className="h-4 w-4" />
                <span>上传文件</span>
                <span className="ml-auto text-xs text-muted-foreground">暂未开放</span>
              </DropdownMenuItem>
              <DropdownMenuItem disabled>
                <Globe className="h-4 w-4" />
                <span>指定网站</span>
                <span className="ml-auto text-xs text-muted-foreground">暂未开放</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
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

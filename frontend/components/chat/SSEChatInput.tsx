'use client'

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
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
import '@/lib/i18n/client'

interface SSEChatInputProps {
  isStreaming: boolean
  sendMessage: (message: string, options?: { activeSmiles?: string | null }) => Promise<void>
  clearTurns: () => void
}

export function SSEChatInput({ isStreaming, sendMessage, clearTurns }: SSEChatInputProps) {
  const { t } = useTranslation('common')
  const [value, setValue] = useState('')
  const [chatSmiles, setChatSmiles] = useState<string | null>(null)
  const { currentSmiles } = useWorkspaceStore()

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
    if (currentSmiles && !chatSmiles) setChatSmiles(currentSmiles)
  }

  const handleRemoveSmiles = () => setChatSmiles(null)

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
        placeholder={t('chat.placeholder')}
        onKeyDown={handleKeyDown}
      />
      <PromptInputActions className="justify-between">
        <PromptInputAction tooltip={t('input.add_datasource')}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 px-2"
                disabled={isStreaming}
                aria-label={t('input.add_datasource')}
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top" className="w-48">
              <DropdownMenuItem
                onClick={handleAddSmiles}
                disabled={!currentSmiles || !!chatSmiles || isStreaming}
              >
                <span>{t('input.add_smiles')}</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled>
                <Upload className="h-4 w-4" />
                <span>{t('input.upload_file')}</span>
                <span className="ml-auto text-xs text-muted-foreground">{t('input.coming_soon')}</span>
              </DropdownMenuItem>
              <DropdownMenuItem disabled>
                <Globe className="h-4 w-4" />
                <span>{t('input.specify_website')}</span>
                <span className="ml-auto text-xs text-muted-foreground">{t('input.coming_soon')}</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </PromptInputAction>

        {isStreaming ? (
          <div className="flex items-center gap-1.5 px-3 text-sm text-muted-foreground">
            <Loader size="sm" />
            <span>{t('input.streaming')}</span>
          </div>
        ) : (
          <PromptInputAction tooltip="">
            <Button
              type="button"
              onClick={handleSubmit}
              size="sm"
              variant="ghost"
              className="h-7 px-2"
              disabled={!value.trim()}
              aria-label={t('input.send')}
            >
              <Send className="h-3.5 w-3.5" />
            </Button>
          </PromptInputAction>
        )}
      </PromptInputActions>
    </PromptInput>
  )
}

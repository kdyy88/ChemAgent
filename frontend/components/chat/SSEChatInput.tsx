'use client'

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Send, X, Plus, Upload, Globe, FlaskConical } from 'lucide-react'
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
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { useSseStore } from '@/store/sseStore'
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
  const turns = useSseStore((s) => s.turns)
  const pendingApproval = turns.at(-1)?.pendingApproval
  const isApprovalPending = !!pendingApproval
  const isFullyDisabled = isStreaming || isApprovalPending

  const handleSubmit = async () => {
    const trimmed = value.trim()
    if (!trimmed || isFullyDisabled) return
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
      disabled={isFullyDisabled}
      className="w-full"
    >
      {isApprovalPending && (
        <div className="flex items-center gap-1.5 px-3 pt-2 text-xs text-orange-600 dark:text-orange-400">
          <span>⏸️</span>
          <span>请先处理上方的审批请求，再发送新消息</span>
        </div>
      )}
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
              disabled={isFullyDisabled}
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
                className="h-7 w-7 rounded-lg text-muted-foreground hover:text-foreground hover:bg-primary/8 transition-colors"
                disabled={isFullyDisabled}
                aria-label={t('input.add_datasource')}
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              side="top"
              sideOffset={6}
              className="w-52 rounded-xl border border-border/60 bg-popover/95 shadow-lg backdrop-blur-sm p-1"
            >
              <DropdownMenuLabel className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                {t('input.add_datasource')}
              </DropdownMenuLabel>
              <DropdownMenuItem
                onClick={handleAddSmiles}
                disabled={!currentSmiles || !!chatSmiles || isStreaming}
                className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm cursor-pointer"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <FlaskConical className="h-3.5 w-3.5" />
                </span>
                <span className="flex-1 truncate">{t('input.add_smiles')}</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator className="my-1 bg-border/40" />
              <DropdownMenuItem
                disabled
                className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm opacity-50 cursor-not-allowed"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                  <Upload className="h-3.5 w-3.5" />
                </span>
                <span className="flex-1 truncate">{t('input.upload_file')}</span>
                <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] leading-none text-muted-foreground">
                  {t('input.coming_soon')}
                </span>
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled
                className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm opacity-50 cursor-not-allowed"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                  <Globe className="h-3.5 w-3.5" />
                </span>
                <span className="flex-1 truncate">{t('input.specify_website')}</span>
                <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] leading-none text-muted-foreground">
                  {t('input.coming_soon')}
                </span>
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

'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Send, X, Plus, Upload, Globe, FlaskConical, Cpu } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputActions,
} from '@/components/ui/prompt-input'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { useSseStore } from '@/store/sseStore'
import { useUIStore } from '@/store/uiStore'
import '@/lib/i18n/client'

interface SSEChatInputProps {
  isStreaming: boolean
  sendMessage: (message: string, options?: import('@/lib/sse-types').SSESendMessageOptions) => Promise<void>
}

function formatTokenCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return `${value}`
}

/** Circular SVG progress ring */
function TokenRing({
  ratio,
  current,
  max,
  sessionTotal,
  modelLabel,
}: {
  ratio: number
  current: number
  max: number
  sessionTotal: number
  modelLabel: string
}) {
  const size = 28
  const strokeW = 2.5
  const r = (size - strokeW) / 2
  const circ = 2 * Math.PI * r
  const dash = circ * Math.min(ratio, 1)
  const percent = Math.round(ratio * 100)

  // colour shifts: teal → amber → red
  const ringColor =
    ratio > 0.85
      ? 'oklch(0.65 0.22 22)'
      : ratio > 0.6
        ? 'oklch(0.78 0.18 82)'
        : 'oklch(0.52 0.145 192)'

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`Context ${percent}% used`}
          className="group relative flex items-center justify-center rounded-full transition-transform duration-150 hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          style={{ width: size, height: size }}
        >
          <svg
            width={size}
            height={size}
            viewBox={`0 0 ${size} ${size}`}
            className="transition-[filter] duration-150 group-hover:[filter:drop-shadow(0_0_4px_var(--color-primary))]"
            style={{ transform: 'rotate(-90deg)' }}
          >
            {/* track */}
            <circle
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke="currentColor"
              strokeWidth={strokeW}
              className="text-border/50"
            />
            {/* progress */}
            {current > 0 && (
              <circle
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                stroke={ringColor}
                strokeWidth={strokeW}
                strokeLinecap="round"
                strokeDasharray={`${dash} ${circ}`}
                style={{ transition: 'stroke-dasharray 0.4s ease, stroke 0.4s ease' }}
              />
            )}
          </svg>
          {/* inner percent label, only when > 0 */}
          {current > 0 && (
            <span
              className="absolute text-[7px] font-semibold tabular-nums leading-none"
              style={{ color: ringColor }}
            >
              {percent > 99 ? '99+' : `${percent}`}
            </span>
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="top"
        sideOffset={10}
        hideArrow
        className="block w-56 overflow-hidden rounded-2xl border border-border/40 bg-popover p-0 shadow-xl backdrop-blur-xl"
      >
        {/* colour-coded top strip */}
        <div style={{ height: 3, background: `linear-gradient(90deg, ${ringColor} 0%, transparent 100%)` }} />

        <div className="px-4 pb-4 pt-3 flex flex-col gap-3.5">

          {/* ── Section 1: Context Window ── */}
          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between">
              <span className="text-[9px] font-semibold uppercase tracking-widest text-muted-foreground/50">
                上下文窗口
              </span>
              <span className="tabular-nums font-bold leading-none" style={{ fontSize: 22, color: ringColor }}>
                {percent}<span style={{ fontSize: 11, fontWeight: 500, opacity: 0.55, marginLeft: 1 }}>%</span>
              </span>
            </div>
            <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(percent, current > 0 ? 2 : 0)}%`,
                  background: ringColor,
                  transition: 'width 0.5s ease',
                }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] tabular-nums text-muted-foreground/60">
              <span>{formatTokenCount(current)} 已用</span>
              <span>{formatTokenCount(max)} 上限</span>
            </div>
          </div>

          {/* divider */}
          <div className="h-px bg-border/40" />

          {/* ── Section 2: Session Cost Reference ── */}
          <div className="flex items-center justify-between">
            <div className="flex flex-col gap-0.5">
              <span className="text-[9px] uppercase tracking-widest text-muted-foreground/50">会话累计</span>
              <span className="text-sm font-semibold tabular-nums text-foreground leading-none">
                {formatTokenCount(sessionTotal)}
              </span>
            </div>
            <div className="flex flex-col items-end gap-0.5">
              <span className="text-[9px] uppercase tracking-widest text-muted-foreground/50">费用参考</span>
              <span className="text-[10px] text-muted-foreground/60 tabular-nums leading-none">
                ≈ ${((sessionTotal / 1_000_000) * 1.75).toFixed(4)}
              </span>
            </div>
          </div>

          {/* model name */}
          {modelLabel && (
            <div className="truncate text-[10px] text-muted-foreground/35 border-t border-border/30 pt-2 -mb-1">
              {modelLabel}
            </div>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  )
}

export function SSEChatInput({ isStreaming, sendMessage }: SSEChatInputProps) {
  const { t } = useTranslation('common')
  const [value, setValue] = useState('')
  const [chatSmiles, setChatSmiles] = useState<string | null>(null)
  const { currentSmiles } = useWorkspaceStore()
  const turns = useSseStore((s) => s.turns)
  const skillsEnabled = useUIStore((s) => s.skillsEnabled)
  const toggleSkills = useUIStore((s) => s.toggleSkills)
  const sessionUsage = useSseStore((s) => s.sessionUsage)
  const lastCallUsage = turns.at(-1)?.usage
  const availableModels = useSseStore((s) => s.availableModels)
  const modelsStatus = useSseStore((s) => s.modelsStatus)
  const modelsError = useSseStore((s) => s.modelsError)
  const selectedModelId = useSseStore((s) => s.selectedModelId)
  const selectModel = useSseStore((s) => s.selectModel)
  const loadAvailableModels = useSseStore((s) => s.loadAvailableModels)
  const pendingApproval = turns.at(-1)?.pendingApproval
  const pendingInterrupt = turns.at(-1)?.pendingInterrupt
  const isApprovalPending = !!pendingApproval
  const isFullyDisabled = isStreaming || isApprovalPending

  useEffect(() => {
    void loadAvailableModels()
  }, [loadAvailableModels])

  const selectedModel = availableModels.find((model) => model.id === selectedModelId) ?? null
  const isModelLocked = isStreaming || !!pendingApproval || !!pendingInterrupt
  const modelButtonLabel =
    modelsStatus === 'loading' ? '加载中…' : selectedModel?.label ?? '选择模型'
  const maxContextTokens = selectedModel?.max_context_tokens ?? 400000
  // 单次调用 total_tokens = 上次发给模型的完整上下文大小，反映上下文是否膨胀
  const lastCallTokens = lastCallUsage?.total_tokens ?? 0
  // 会话累计 = 所有调用 input+output 累加，用于估算费用
  const sessionTotalTokens = sessionUsage.total_tokens
  const tokenUsageRatio = useMemo(
    () => (maxContextTokens > 0 ? Math.min(lastCallTokens / maxContextTokens, 1) : 0),
    [lastCallTokens, maxContextTokens],
  )

  const handleSubmit = async () => {
    const trimmed = value.trim()
    if (!trimmed || isFullyDisabled) return
    setValue('')
    await sendMessage(trimmed, { activeSmiles: chatSmiles ?? null, skillsEnabled })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSubmit()
    }
  }

  const handleAddSmiles = () => {
    if (currentSmiles && !chatSmiles) setChatSmiles(currentSmiles)
  }

  const handleRemoveSmiles = () => setChatSmiles(null)

  const smilesLabel = chatSmiles
    ? chatSmiles.slice(0, 22) + (chatSmiles.length > 22 ? '…' : '')
    : ''

  const canSend = !!value.trim() && !isFullyDisabled

  return (
    <PromptInput
      value={value}
      onValueChange={setValue}
      isLoading={isStreaming}
      onSubmit={handleSubmit}
      disabled={isFullyDisabled}
      className="w-full"
    >
      {/* Approval notice */}
      {isApprovalPending && (
        <div className="flex items-center gap-1.5 px-3 pt-2.5 text-xs text-orange-500 dark:text-orange-400">
          <span>⏸</span>
          <span>请先处理上方的审批请求，再发送新消息</span>
        </div>
      )}

      {/* Attached SMILES badge */}
      {chatSmiles && (
        <div className="flex items-center gap-2 px-3 pt-2.5 pb-0.5">
          <Badge
            variant="outline"
            className="h-6 gap-1.5 rounded-full border-primary/25 bg-primary/8 px-2.5 font-mono text-[11px] text-primary"
            title={chatSmiles}
          >
            <FlaskConical className="h-3 w-3 shrink-0" />
            {smilesLabel}
            <button
              onClick={handleRemoveSmiles}
              disabled={isFullyDisabled}
              className="ml-0.5 -mr-1 flex h-4 w-4 items-center justify-center rounded-full transition-colors hover:bg-primary/20 disabled:opacity-40"
              aria-label="Remove SMILES"
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </Badge>
        </div>
      )}

      <PromptInputTextarea
        placeholder={t('chat.placeholder')}
        onKeyDown={handleKeyDown}
      />

      <PromptInputActions className="items-center justify-between px-1 pb-1">
        {/* ── Left cluster ── */}
        <div className="flex items-center gap-1">
          {/* + Add datasource */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="h-8 w-8 rounded-xl text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary disabled:opacity-40"
                disabled={isFullyDisabled}
                aria-label={t('input.add_datasource')}
              >
                <Plus className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              side="top"
              sideOffset={8}
              className="w-52 rounded-2xl border border-border/60 bg-popover/95 p-1.5 shadow-xl backdrop-blur-sm"
            >
              <DropdownMenuLabel className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/60">
                {t('input.add_datasource')}
              </DropdownMenuLabel>
              <DropdownMenuItem
                onClick={handleAddSmiles}
                disabled={!currentSmiles || !!chatSmiles || isStreaming}
                className="flex cursor-pointer items-center gap-2.5 rounded-xl px-2 py-2 text-sm"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <FlaskConical className="h-3.5 w-3.5" />
                </span>
                <span className="flex-1 truncate">{t('input.add_smiles')}</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator className="my-1 bg-border/40" />
              <DropdownMenuItem
                disabled
                className="flex cursor-not-allowed items-center gap-2.5 rounded-xl px-2 py-2 text-sm opacity-40"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  <Upload className="h-3.5 w-3.5" />
                </span>
                <span className="flex-1 truncate">{t('input.upload_file')}</span>
                <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[9px] leading-none text-muted-foreground">
                  {t('input.coming_soon')}
                </span>
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled
                className="flex cursor-not-allowed items-center gap-2.5 rounded-xl px-2 py-2 text-sm opacity-40"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  <Globe className="h-3.5 w-3.5" />
                </span>
                <span className="flex-1 truncate">{t('input.specify_website')}</span>
                <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[9px] leading-none text-muted-foreground">
                  {t('input.coming_soon')}
                </span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Skills toggle */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={toggleSkills}
                disabled={isFullyDisabled}
                aria-label={skillsEnabled ? 'Skills 已启用' : 'Skills 已禁用'}
                className={[
                  'h-8 w-8 rounded-xl transition-colors',
                  skillsEnabled
                    ? 'border border-primary/30 bg-primary/15 text-primary hover:bg-primary/20'
                    : 'text-muted-foreground hover:bg-primary/10 hover:text-primary disabled:opacity-40',
                ].join(' ')}
              >
                <FlaskConical className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top" sideOffset={8}>
              <p className="text-xs">{skillsEnabled ? 'Skills 已启用' : 'Skills 已禁用（点击开启）'}</p>
            </TooltipContent>
          </Tooltip>

          {/* Model selector */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-8 max-w-44 gap-1.5 rounded-xl border border-border/50 bg-muted/40 px-2.5 text-xs font-medium text-muted-foreground shadow-none transition-colors hover:bg-primary/10 hover:text-primary disabled:opacity-40"
                disabled={isModelLocked || modelsStatus === 'loading' || availableModels.length === 0}
                aria-label="选择模型"
                title={selectedModel?.id ?? modelButtonLabel}
              >
                <Cpu className="h-3 w-3 shrink-0 opacity-70" />
                <span className="truncate">{modelButtonLabel}</span>
                <ChevronDown className="h-3 w-3 shrink-0 opacity-50" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              side="top"
              sideOffset={8}
              className="w-60 rounded-2xl border border-border/60 bg-popover/95 p-1.5 shadow-xl backdrop-blur-sm"
            >
              <DropdownMenuLabel className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground/60">
                模型选择
              </DropdownMenuLabel>
              <DropdownMenuSeparator className="my-1 bg-border/50" />
              {availableModels.map((model) => (
                <DropdownMenuCheckboxItem
                  key={model.id}
                  checked={selectedModelId === model.id}
                  onCheckedChange={() => selectModel(model.id)}
                  className="rounded-xl px-2 py-2 text-sm"
                >
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    <span className="truncate">{model.label}</span>
                    {model.is_default && (
                      <Badge variant="secondary" className="text-[9px]">
                        默认
                      </Badge>
                    )}
                  </div>
                </DropdownMenuCheckboxItem>
              ))}
              {availableModels.length === 0 && (
                <div className="px-2 py-2 text-xs text-muted-foreground">
                  {modelsError || '暂无可选模型'}
                </div>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* ── Right cluster ── */}
        <div className="flex items-center gap-2">
          {/* Token ring — always visible, purely decorative when usage=0 */}
          <TokenRing
            ratio={tokenUsageRatio}
            current={lastCallTokens}
            max={maxContextTokens}
            sessionTotal={sessionTotalTokens}
            modelLabel={selectedModel?.label ?? ''}
          />

          {/* divider */}
          <div className="h-4 w-px bg-border/50" />

          {/* Send / streaming indicator */}
          {isStreaming ? (
            <div className="flex h-8 w-8 items-center justify-center">
              {/* Animated pulse dots */}
              <span className="flex gap-0.5">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="block h-1.5 w-1.5 rounded-full bg-primary"
                    style={{
                      animation: 'bounce 1.2s ease-in-out infinite',
                      animationDelay: `${i * 0.2}s`,
                    }}
                  />
                ))}
              </span>
            </div>
          ) : (
            <Button
              type="button"
              onClick={handleSubmit}
              size="icon"
              className="h-8 w-8 rounded-xl bg-primary text-primary-foreground shadow-sm transition-all hover:bg-primary/90 hover:shadow-md disabled:opacity-30"
              disabled={!canSend}
              aria-label={t('input.send')}
            >
              <Send className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </PromptInputActions>
    </PromptInput>
  )
}

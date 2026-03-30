'use client'

import { useEffect, useMemo, useState } from 'react'
import { Beaker, Brain, FlaskConical, Hammer, Sparkles } from 'lucide-react'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ui/reasoning'
import { Steps, StepsBar, StepsContent, StepsItem, StepsTrigger } from '@/components/ui/steps'
import type { SSEThinking } from '@/lib/sse-types'

function MetaBadge({ children, highlight }: { children: React.ReactNode; highlight?: boolean }) {
  return (
    <span
      className={`rounded-full px-1.5 py-0.5 text-[10px] leading-none ${
        highlight
          ? 'bg-primary/10 text-primary/70'
          : 'bg-muted/70 text-muted-foreground/70'
      }`}
    >
      {children}
    </span>
  )
}

interface ResearchThinkingProps {
  steps: SSEThinking[]
  isStreaming: boolean
}

interface ThinkingGroup {
  id: string
  detail: string
  title: string
  caption: string
  count: number
  kind: 'tool' | 'llm' | 'other'
  isStreaming: boolean
}

type TimelineBlock =
  | { kind: 'single'; id: string; item: ThinkingGroup }
  | { kind: 'tool_sequence'; id: string; items: ThinkingGroup[] }

function summarizeHeaderTitle(isStreaming: boolean): string {
  return isStreaming ? '思考中' : '思考记录'
}

function summarizeGroupTitle(step: SSEThinking): string {
  const raw = step.text.trim()
  if (!raw) return '处理中'

  if (step.category === 'llm') {
    // If the text starts with **Title** ... extract only the bold part as the title.
    // This prevents leaking raw LLM inner monologue ("**Processing drug data** I'm thinking...").
    const leadingBold = raw.match(/^\*\*(.+?)\*\*/)
    if (leadingBold) return leadingBold[1]
    // No leading bold — strip inline markdown and truncate
    const plain = raw.replace(/\*\*(.+?)\*\*/g, '$1').replace(/\*(.+?)\*/g, '$1').trim()
    return plain.length > 56 ? `${plain.slice(0, 56).trimEnd()}…` : plain
  }

  // Strip markdown for tool/other categories
  const text = raw.replace(/\*\*(.+?)\*\*/g, '$1').replace(/\*(.+?)\*/g, '$1').trim()
  if (!text) return '处理中'

  if (step.category === 'tool') {
    return text.replace(/^正在调用：/, '').replace(/^工具完成：/, '')
  }

  return text.length > 42 ? `${text.slice(0, 42).trimEnd()}…` : text
}

function stripLeadingTitle(raw: string): string {
  // Remove a leading **Title** or **Title**\n from content so it doesn't show twice.
  return raw.replace(/^\*\*[^*]+\*\*\s*\n?/, '').trim()
}

function groupThinkingSteps(steps: SSEThinking[]): ThinkingGroup[] {
  const timeline: ThinkingGroup[] = []

  for (const step of steps) {
    const kind: ThinkingGroup['kind'] =
      step.category === 'tool' ? 'tool' : step.category === 'llm' ? 'llm' : 'other'
    const groupId = `${kind}:${step.group_key || step.source || step.category || summarizeGroupTitle(step)}`
    const latestText = summarizeGroupTitle(step)
    const cleanDetail = step.category === 'llm' ? stripLeadingTitle(step.text.trim()) : step.text.trim()
    const lastGroup = timeline[timeline.length - 1]

    if (lastGroup && lastGroup.id === groupId) {
      lastGroup.detail = cleanDetail || lastGroup.detail
      lastGroup.title = latestText || lastGroup.title
      lastGroup.caption = step.source === 'llm_reasoning' ? '模型摘要' : lastGroup.caption
      lastGroup.count += 1
      lastGroup.isStreaming = step.done !== true
      continue
    }

    timeline.push({
      id: groupId,
      detail: cleanDetail || latestText,
      title: latestText,
      caption: step.source === 'llm_reasoning' ? '模型摘要' : kind === 'tool' ? '化学操作' : '执行动态',
      count: 1,
      kind,
      isStreaming: step.done !== true,
    })
  }

  // Any group that is not the last is definitively done —
  // a newer group having started proves the previous finished.
  for (let i = 0; i < timeline.length - 1; i++) {
    timeline[i].isStreaming = false
  }

  return timeline
}

function groupIcon(kind: ThinkingGroup['kind']) {
  if (kind === 'tool') return FlaskConical
  if (kind === 'llm') return Brain
  return Sparkles
}

function stepStatusText(group: ThinkingGroup): string | null {
  return group.isStreaming ? '状态：进行中' : null
}

function buildTimelineBlocks(timeline: ThinkingGroup[]): TimelineBlock[] {
  const blocks: TimelineBlock[] = []

  for (const group of timeline) {
    const lastBlock = blocks[blocks.length - 1]

    if (group.kind === 'tool') {
      if (lastBlock?.kind === 'tool_sequence') {
        lastBlock.items.push(group)
      } else {
        blocks.push({
          kind: 'tool_sequence',
          id: `tools:${group.id}`,
          items: [group],
        })
      }
      continue
    }

    blocks.push({
      kind: 'single',
      id: `single:${group.id}`,
      item: group,
    })
  }

  return blocks
}

export function ResearchThinking({ steps, isStreaming }: ResearchThinkingProps) {
  const [openSteps, setOpenSteps] = useState<Record<string, boolean>>({})
  const timeline = useMemo(() => groupThinkingSteps(steps), [steps])
  const blocks = useMemo(() => buildTimelineBlocks(timeline), [timeline])
  const headerTitle = summarizeHeaderTitle(isStreaming)

  // Derive the key of the currently streaming block (always the last one).
  const activeBlockKey = useMemo(() => {
    for (let i = blocks.length - 1; i >= 0; i--) {
      const block = blocks[i]
      const streaming =
        block.kind === 'tool_sequence'
          ? block.items.some((item) => item.isStreaming)
          : block.item.isStreaming
      if (streaming) return `${block.id}-${i}`
    }
    return null
  }, [blocks])

  // When the active block changes, clear user overrides so the auto-open logic takes effect.
  useEffect(() => {
    if (!activeBlockKey) return
    setOpenSteps({})
  }, [activeBlockKey])

  if (timeline.length === 0) return null

  return (
    <div className="w-full space-y-2">
      {/* Header: icon + stacked title/hint on left, stage count on right */}
      <div className="flex items-start justify-between gap-2 px-1">
        <div className="flex items-start gap-1.5">
          <Beaker className="mt-0.5 size-4 shrink-0 text-muted-foreground/70" />
          <div className="space-y-0.5">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-foreground/80">{headerTitle}</span>
              {isStreaming && (
                <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] leading-none text-primary/70">
                  输出中
                </span>
              )}
            </div>
            <p className="text-[10px] leading-tight text-muted-foreground/55">
              {isStreaming ? '思考内容正在实时输出' : '展开可查看完整思考与工具步骤'}
            </p>
          </div>
        </div>
        <span className="shrink-0 pt-0.5 text-[10px] tabular-nums text-muted-foreground/60">
          {timeline.length} 个阶段
        </span>
      </div>

      <div className="w-full space-y-1.5">
        {blocks.map((block, blockIndex) => {
          if (block.kind === 'tool_sequence') {
            const stepKey = `${block.id}-${blockIndex}`
            const stepOpen = openSteps[stepKey] ?? (stepKey === activeBlockKey)
            const activeTitle = block.items.find((item) => item.isStreaming)?.title ?? block.items.at(-1)?.title ?? '工具调用'

            return (
              <Steps
                key={stepKey}
                open={stepOpen}
                onOpenChange={(nextOpen) => {
                  setOpenSteps((current) => ({ ...current, [stepKey]: nextOpen }))
                }}
                className="w-full px-3 py-2 shadow-none"
              >
                <StepsTrigger leftIcon={<Hammer className="size-4" />} className="text-xs">
                  <span className="flex min-w-0 flex-1 items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-foreground/80">{activeTitle}</span>
                    <span className="shrink-0 rounded-full bg-muted/80 px-1.5 py-0.5 text-[10px] tabular-nums text-muted-foreground/70">
                      {block.items.length} 步
                    </span>
                  </span>
                </StepsTrigger>

                <StepsContent className="w-full" bar={<StepsBar className="mr-2 ml-1.5" />}>
                  <div className="space-y-0.5 pt-0.5">
                    {block.items.map((item, itemIndex) => {
                      const mergedText = item.count > 1 ? `合并 ${item.count} 条` : null

                      return (
                        <StepsItem key={`${item.id}-${itemIndex}`} className="text-xs">
                          <div className="flex items-center justify-between gap-2 py-0.5">
                            <div className="flex items-center gap-1.5 min-w-0 text-foreground/75">
                              <FlaskConical className="h-3 w-3 shrink-0 text-muted-foreground/50" aria-hidden="true" />
                              <span className="min-w-0 truncate">{item.title}</span>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              <MetaBadge>{item.caption}</MetaBadge>
                              {mergedText && <MetaBadge>{mergedText}</MetaBadge>}
                              {isStreaming && item.isStreaming && <MetaBadge highlight>进行中</MetaBadge>}
                            </div>
                          </div>
                        </StepsItem>
                      )
                    })}
                  </div>
                </StepsContent>
              </Steps>
            )
          }

          const group = block.item
          const Icon = groupIcon(group.kind)
          const stepKey = `${block.id}-${blockIndex}`
          const stepOpen = openSteps[stepKey] ?? (stepKey === activeBlockKey)
          const mergedText = group.count > 1 ? `已合并 ${group.count} 条同类更新` : null
          const statusText = stepStatusText(group)

          if (group.kind === 'llm') {
            return (
              <Reasoning
                key={stepKey}
                open={stepOpen}
                onOpenChange={(nextOpen) => {
                  setOpenSteps((current) => ({ ...current, [stepKey]: nextOpen }))
                }}
                className="w-full px-3 py-2 shadow-none"
                isStreaming={isStreaming && group.isStreaming}
              >
                <ReasoningTrigger className="w-full text-left text-xs text-muted-foreground/90 hover:text-foreground">
                  <span className="flex min-w-0 flex-1 items-center gap-2">
                    <Icon className="size-3.5 shrink-0 text-muted-foreground/60" />
                    <span className="min-w-0 flex-1 truncate text-foreground/80">{group.title}</span>
                    {isStreaming && group.isStreaming && (
                      <span className="shrink-0 text-[10px] text-primary/60">进行中</span>
                    )}
                  </span>
                </ReasoningTrigger>

                <ReasoningContent
                  className="mt-2 w-full"
                  contentClassName="w-full max-w-none space-y-2 border-l border-border/40 pl-3 text-xs leading-relaxed"
                >
                  <div className="whitespace-pre-wrap break-words text-foreground/75">{group.detail}</div>
                  <div className="flex flex-wrap items-center gap-1">
                    <MetaBadge>{group.caption}</MetaBadge>
                    {mergedText && <MetaBadge>{mergedText}</MetaBadge>}
                    {isStreaming && statusText && <MetaBadge highlight>{statusText}</MetaBadge>}
                  </div>
                </ReasoningContent>
              </Reasoning>
            )
          }

          return (
            <Reasoning
              key={stepKey}
              open={stepOpen}
              onOpenChange={(nextOpen) => {
                setOpenSteps((current) => ({ ...current, [stepKey]: nextOpen }))
              }}
              className="w-full px-3 py-2 shadow-none"
            >
              <ReasoningTrigger className="w-full text-left text-xs text-muted-foreground/90 hover:text-foreground">
                <span className="flex min-w-0 flex-1 items-center gap-2">
                  <Icon className="size-3.5 shrink-0 text-muted-foreground/60" />
                  <span className="min-w-0 flex-1 truncate text-foreground/80">{group.title}</span>
                  {isStreaming && group.isStreaming && (
                    <span className="shrink-0 text-[10px] text-primary/60">进行中</span>
                  )}
                </span>
              </ReasoningTrigger>

              <ReasoningContent
                className="mt-2 w-full"
                contentClassName="w-full max-w-none space-y-2 border-l border-border/40 pl-3 text-xs leading-relaxed"
              >
                <div className="whitespace-pre-wrap break-words text-foreground/75">{group.detail}</div>
                <div className="flex flex-wrap items-center gap-1">
                  <MetaBadge>{group.caption}</MetaBadge>
                  {mergedText && <MetaBadge>{mergedText}</MetaBadge>}
                  {isStreaming && statusText && <MetaBadge highlight>{statusText}</MetaBadge>}
                </div>
              </ReasoningContent>
            </Reasoning>
          )
        })}
      </div>
    </div>
  )
}
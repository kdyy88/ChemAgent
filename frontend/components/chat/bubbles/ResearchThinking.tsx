'use client'

import { useMemo, useState } from 'react'
import { Beaker, Brain, FlaskConical, Hammer, Sparkles } from 'lucide-react'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ui/reasoning'
import { Steps, StepsBar, StepsContent, StepsItem, StepsTrigger } from '@/components/ui/steps'
import type { SSEThinking } from '@/lib/sse-types'

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
  const text = step.text.trim()
  if (!text) return '处理中'

  if (step.category === 'llm') {
    return text.length > 56 ? `${text.slice(0, 56).trimEnd()}…` : text
  }

  if (step.category === 'tool') {
    return text.replace(/^正在调用：/, '').replace(/^工具完成：/, '')
  }

  return text.length > 42 ? `${text.slice(0, 42).trimEnd()}…` : text
}

function groupThinkingSteps(steps: SSEThinking[]): ThinkingGroup[] {
  const timeline: ThinkingGroup[] = []

  for (const step of steps) {
    const kind: ThinkingGroup['kind'] =
      step.category === 'tool' ? 'tool' : step.category === 'llm' ? 'llm' : 'other'
    const groupId = `${kind}:${step.group_key || step.source || step.category || summarizeGroupTitle(step)}`
    const latestText = summarizeGroupTitle(step)
    const lastGroup = timeline[timeline.length - 1]

    if (lastGroup && lastGroup.id === groupId) {
      lastGroup.detail = step.text.trim() || lastGroup.detail
      lastGroup.title = latestText || lastGroup.title
      lastGroup.caption = step.source === 'llm_reasoning' ? '模型摘要' : lastGroup.caption
      lastGroup.count += 1
      lastGroup.isStreaming = step.done !== true
      continue
    }

    timeline.push({
      id: groupId,
      detail: step.text.trim() || latestText,
      title: latestText,
      caption: step.source === 'llm_reasoning' ? '模型摘要' : kind === 'tool' ? '化学操作' : '执行动态',
      count: 1,
      kind,
      isStreaming: step.done !== true,
    })
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

  if (timeline.length === 0) return null

  return (
    <div className="w-full space-y-2">
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground/80">
        <Beaker className="size-4" />
        <span className="font-medium">{headerTitle}</span>
        <span>{isStreaming ? '思考内容正在实时输出' : '展开可查看完整思考与工具步骤'}</span>
        <span className="ml-auto shrink-0">{timeline.length} 个阶段</span>
      </div>

      <div className="w-full space-y-2">
        {blocks.map((block, blockIndex) => {
          if (block.kind === 'tool_sequence') {
            const stepKey = `${block.id}-${blockIndex}`
            const stepOpen = openSteps[stepKey] ?? block.items.some((item) => item.isStreaming)
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
                    <span className="shrink-0 text-[10px] text-muted-foreground/80">{block.items.length} 个工具步骤</span>
                  </span>
                </StepsTrigger>

                <StepsContent className="w-full" bar={<StepsBar className="mr-2 ml-1.5" />}>
                  <div className="space-y-1">
                    {block.items.map((item, itemIndex) => {
                      const mergedText = item.count > 1 ? `已合并 ${item.count} 条同类更新` : null
                      const statusText = stepStatusText(item)

                      return (
                        <StepsItem key={`${item.id}-${itemIndex}`} className="space-y-1 text-xs">
                          <div className="flex items-center gap-2 text-foreground/80">
                            <FlaskConical className="h-3.5 w-3.5 shrink-0 text-muted-foreground/75" />
                            <span className="min-w-0 flex-1 break-words">{item.title}</span>
                          </div>
                          <div className="whitespace-pre-wrap break-words pl-[1.35rem] leading-5 text-foreground/75">
                            {item.detail}
                          </div>
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 pl-[1.35rem] text-[10px] text-muted-foreground/75">
                            <span>{item.caption}</span>
                            {mergedText ? <span>{mergedText}</span> : null}
                            {statusText ? <span>{statusText}</span> : null}
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
          const stepOpen = openSteps[stepKey] ?? group.isStreaming
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
                isStreaming={group.isStreaming}
              >
                <ReasoningTrigger className="w-full justify-between text-left text-xs text-muted-foreground/90 hover:text-foreground">
                  <span className="flex min-w-0 flex-1 items-center gap-2">
                    <span className="flex shrink-0 items-center gap-2">
                      <Icon className="size-4 text-muted-foreground" />
                    </span>
                    <span className="min-w-0 flex-1 truncate text-foreground/80">{group.title}</span>
                    {group.isStreaming ? <span className="shrink-0 text-[10px] text-foreground/70">进行中</span> : null}
                  </span>
                </ReasoningTrigger>

                <ReasoningContent
                  className="mt-2 w-full"
                  contentClassName="w-full max-w-none space-y-2 border-l border-border/40 pl-3 text-xs leading-relaxed whitespace-pre-wrap"
                >
                  <div className="break-words text-foreground/80">{group.detail}</div>
                  <div className="text-[11px] text-muted-foreground/80">{group.caption}</div>
                  {mergedText ? <div className="text-[11px] text-muted-foreground/80">{mergedText}</div> : null}
                  {statusText ? <div className="text-[11px] text-muted-foreground/80">{statusText}</div> : null}
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
              <ReasoningTrigger className="w-full justify-between text-left text-xs text-muted-foreground/90 hover:text-foreground">
                <span className="flex min-w-0 flex-1 items-center gap-2">
                  <span className="flex shrink-0 items-center gap-2">
                    <Icon className="size-4 text-muted-foreground" />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-foreground/80">{group.title}</span>
                  {group.isStreaming ? <span className="shrink-0 text-[10px] text-foreground/70">进行中</span> : null}
                </span>
              </ReasoningTrigger>

              <ReasoningContent
                className="mt-2 w-full"
                contentClassName="w-full max-w-none space-y-2 border-l border-border/40 pl-3 text-xs leading-relaxed whitespace-pre-wrap"
              >
                <div className="break-words text-foreground/80">{group.detail}</div>
                <div className="text-[11px] text-muted-foreground/80">{group.caption}</div>
                {mergedText ? <div className="text-[11px] text-muted-foreground/80">{mergedText}</div> : null}
                {statusText ? <div className="text-[11px] text-muted-foreground/80">{statusText}</div> : null}
              </ReasoningContent>
            </Reasoning>
          )
        })}
      </div>
    </div>
  )
}
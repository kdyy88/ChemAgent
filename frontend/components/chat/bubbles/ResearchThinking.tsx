'use client'

import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { SSEThinking, WebSearchSourcesArtifact } from '@/lib/sse-types'
import '@/lib/i18n/client'

type TFn = (key: string, opts?: Record<string, unknown>) => string

type StageKind = 'research' | 'analysis' | 'validation' | 'coordination' | 'wrapup' | 'error'

interface ThinkingGroup {
  id: string
  rawText: string
  detail: string
  category?: SSEThinking['category']
  source?: string
  count: number
  isStreaming: boolean
}

interface DisplayEntry {
  id: string
  title: string
  summary: string
  reasoningText: string
  isStreaming: boolean
  isSubAgent: boolean
  count: number
  sourceQuery?: string
  sourceLinks: Array<{ title: string; url: string }>
}

interface ResearchThinkingProps {
  steps: SSEThinking[]
  isStreaming: boolean
  webSources?: WebSearchSourcesArtifact[]
}

function summarizeHeaderTitle(isStreaming: boolean, t: TFn): string {
  return isStreaming ? t('thinking_panel.header_streaming') : t('thinking_panel.header_done')
}

function toPlainText(raw: string): string {
  return raw
    .replace(/^\*\*[^*]+\*\*\s*/m, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/`(.+?)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

function toDisplayText(raw: string): string {
  return raw
    .replace(/^\*\*(.+?)\*\*\s*$/gm, '$1')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/`(.+?)`/g, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function clipText(value: string, limit: number): string {
  if (value.length <= limit) return value
  return `${value.slice(0, limit).trimEnd()}…`
}

function summarizeGroupTitle(step: SSEThinking, t: TFn): string {
  const raw = toPlainText(step.text || '')
  if (!raw) return t('thinking_panel.processing')
  return clipText(raw, step.category === 'llm' ? 72 : 52)
}

function normalizeDetail(step: SSEThinking): string {
  const text = toPlainText(step.text || '')
  if (!text) return ''
  return text
    .replace(/^正在调用：/, '')
    .replace(/^工具完成：/, '')
    .replace(/^Preparing response in Chinese/i, '正在整理最终回答')
    .replace(/^Clarifying .*$/i, '正在澄清并核对结构约束')
    .replace(/^Computing descriptors/i, '正在核对候选分子的性质')
    .replace(/^Updating task statuses/i, '正在整理已经确认的阶段结论')
}

function groupThinkingSteps(steps: SSEThinking[], t: TFn): ThinkingGroup[] {
  const timeline: ThinkingGroup[] = []

  for (const step of steps) {
    const groupId = `${step.group_key || step.source || step.category || summarizeGroupTitle(step, t)}`
    const latestText = summarizeGroupTitle(step, t)
    const cleanDetail = normalizeDetail(step)
    const lastGroup = timeline[timeline.length - 1]

    if (lastGroup && lastGroup.id === groupId) {
      lastGroup.detail = cleanDetail || lastGroup.detail
      lastGroup.rawText = `${lastGroup.rawText}\n${step.text || ''}`.trim()
      lastGroup.category = step.category
      lastGroup.source = step.source
      lastGroup.count += 1
      lastGroup.isStreaming = step.done !== true
      continue
    }

    timeline.push({
      id: groupId,
      rawText: step.text || '',
      detail: cleanDetail || latestText,
      category: step.category,
      source: step.source,
      count: 1,
      isStreaming: step.done !== true,
    })
  }

  for (let i = 0; i < timeline.length - 1; i++) {
    timeline[i].isStreaming = false
  }

  return timeline
}

function inferStageKind(raw: string): StageKind {
  const text = raw.toLowerCase()

  if (/(error|失败|异常|中断)/.test(text)) return 'error'
  if (/(response|最终回答|输出给用户|preparing response|中文)/.test(text)) return 'wrapup'
  if (/(sub[_ -]?agent|子智能体|parallel|delegat)/.test(text)) return 'coordination'
  if (/(web[_ -]?search|搜索|pubchem|公开资料|来源)/.test(text)) return 'research'
  if (/(substructure|smarts|咪唑|约束|descriptor|property|lipinski|pains|validate|验证|核对性质)/.test(text)) return 'validation'
  if (/(planner|task_router|复杂度|规划|清单|任务状态|update task|update_task_status)/.test(text)) return 'coordination'
  return 'analysis'
}

function inferStageTitle(kind: StageKind): string {
  switch (kind) {
    case 'research':
      return '补充背景资料'
    case 'analysis':
      return '整理线索与方案'
    case 'validation':
      return '核对关键限制'
    case 'coordination':
      return '同步中间进展'
    case 'wrapup':
      return '整理最终表达'
    case 'error':
      return '处理中遇到问题'
  }
}

function inferStageSummary(kind: StageKind, isStreaming: boolean, count: number): string {
  const multi = count > 1

  if (isStreaming) {
    switch (kind) {
      case 'research':
        return multi ? '正在持续补充资料并交叉核对。' : '正在补充资料并确认关键事实。'
      case 'analysis':
        return '正在整合线索，收敛成判断。'
      case 'validation':
        return '正在核对结构限制和候选条件。'
      case 'coordination':
        return '正在同步阶段结果，准备衔接下一步。'
      case 'wrapup':
        return '正在把已确认内容整理成最终回答。'
      case 'error':
        return '这里出现了阻塞，正在判断是否继续。'
    }
  }

  switch (kind) {
    case 'research':
      return multi ? '已补充多轮背景资料。' : '已补充一轮背景资料。'
    case 'analysis':
      return '已整理出当前阶段的关键判断。'
    case 'validation':
      return '已完成关键核对。'
    case 'coordination':
      return '已把中间结果接回主流程。'
    case 'wrapup':
      return '已进入最终表述整理。'
    case 'error':
      return '这一段流程出现了问题。'
  }
}

function isSubAgentStep(group: ThinkingGroup): boolean {
  const source = String(group.source || '').toLowerCase()
  return source.includes('sub_agent')
}

function isSubAgentReportStep(group: ThinkingGroup): boolean {
  const source = String(group.source || '').toLowerCase()
  return source.includes('sub_agent_report')
}

function looksLikeSearchStep(raw: string): boolean {
  const text = raw.toLowerCase()
  return /(web[_ -]?search|搜索|searching|looking up|查找|检索)/.test(text)
}

function buildDisplayEntries(
  timeline: ThinkingGroup[],
  webSources?: WebSearchSourcesArtifact[],
): DisplayEntry[] {
  let sourceCursor = 0

  return timeline.map((group) => {
    const raw = `${group.rawText}\n${group.detail}`.trim()
    const kind = inferStageKind(raw)
    const reasoningText =
      group.category === 'llm' || group.source === 'llm_reasoning' || isSubAgentReportStep(group)
        ? toDisplayText(group.rawText)
        : ''
    const matchedSourceArtifact =
      kind === 'research' && looksLikeSearchStep(raw) ? webSources?.[sourceCursor] : undefined

    if (matchedSourceArtifact) {
      sourceCursor += 1
    }

    const sourceLinks = (matchedSourceArtifact?.sources || []).map((source) => ({
      title: source.title || source.url,
      url: source.url,
    }))

    return {
      id: group.id,
      title: isSubAgentReportStep(group) ? '子任务结果返回' : inferStageTitle(kind),
      summary: isSubAgentReportStep(group)
        ? (group.isStreaming ? '子智能体正在整理本轮结果。' : '子智能体已返回本轮结论。')
        : inferStageSummary(kind, group.isStreaming, group.count),
      reasoningText,
      isStreaming: group.isStreaming,
      isSubAgent: isSubAgentStep(group),
      count: group.count,
      sourceQuery: matchedSourceArtifact?.query,
      sourceLinks,
    }
  })
}

function statusLabel(isStreaming: boolean): string {
  return isStreaming ? '进行中' : '已完成'
}

function statusTone(isStreaming: boolean): string {
  return isStreaming ? 'text-foreground/72' : 'text-muted-foreground/62'
}

export function ResearchThinking({ steps, isStreaming, webSources }: ResearchThinkingProps) {
  const { t } = useTranslation('agent')
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tFn: TFn = (key, opts) => t(key as any, opts as any) as string
  const timeline = useMemo(() => groupThinkingSteps(steps, tFn), [steps, tFn])
  const entries = useMemo(() => buildDisplayEntries(timeline, webSources), [timeline, webSources])
  const headerTitle = summarizeHeaderTitle(isStreaming, tFn)

  if (entries.length === 0) return null

  return (
    <div className="w-full px-1 pt-0.5 text-xs">
      <div className="mb-2 flex items-center gap-2 text-[11px] text-muted-foreground/62">
        <span className="font-medium text-muted-foreground/72">{headerTitle}</span>
        <span className="text-muted-foreground/45">/</span>
        <span>{isStreaming ? '中间过程持续追加中' : '按发生顺序保留'}</span>
      </div>

      <div className="space-y-3">
        {entries.map((entry, index) => (
          <div
            key={`${entry.id}-${index}`}
            className={`relative ${entry.isSubAgent ? 'ml-5 pl-5' : 'pl-4'}`}
          >
            <span
              className={`absolute top-[0.45rem] size-1.5 rounded-full ${entry.isSubAgent ? 'left-1 bg-foreground/28' : 'left-0'} ${entry.isStreaming ? 'bg-foreground/45' : 'bg-border'}`}
              aria-hidden="true"
            />
            {index < entries.length - 1 && (
              <span
                className={`absolute top-[0.95rem] bottom-[-0.9rem] w-px bg-border/65 ${entry.isSubAgent ? 'left-[0.42rem]' : 'left-[0.18rem]'}`}
                aria-hidden="true"
              />
            )}

            <div className={`space-y-1 ${entry.isSubAgent ? 'border-l border-border/55 pl-3' : ''}`}>
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[11px] leading-relaxed">
                {entry.isSubAgent && <span className="text-muted-foreground/48">子智能体</span>}
                <span className="font-medium text-foreground/74">{entry.title}</span>
                <span className={statusTone(entry.isStreaming)}>{statusLabel(entry.isStreaming)}</span>
                {entry.count > 1 && <span className="text-muted-foreground/52">更新 {entry.count} 次</span>}
              </div>

              <p className="text-[11px] leading-relaxed text-muted-foreground/76">{entry.summary}</p>

              {entry.reasoningText && (
                <div className="border-l border-border/70 pl-3 pt-0.5">
                  <div className="whitespace-pre-wrap break-words text-[11px] leading-6 text-foreground/70">
                    {entry.reasoningText}
                  </div>
                </div>
              )}

              {entry.sourceQuery && (
                <p className="text-[10px] leading-relaxed text-muted-foreground/55">
                  检索主题：{entry.sourceQuery}
                </p>
              )}

              {entry.sourceLinks.length > 0 && (
                <div className="text-[10px] leading-5 text-muted-foreground/58">
                  <span className="mr-1 text-muted-foreground/48">参考来源：</span>
                  {entry.sourceLinks.map((source, sourceIndex) => (
                    <span key={`${source.url}-${sourceIndex}`}>
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline decoration-border underline-offset-2 transition-colors hover:text-foreground/76"
                      >
                        {clipText(source.title, 42)}
                      </a>
                      {sourceIndex < entry.sourceLinks.length - 1 ? <span className="text-muted-foreground/38">，</span> : null}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
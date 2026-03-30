'use client'

import { useState } from 'react'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ui/reasoning'
import type { SSEThinking } from '@/lib/sse-types'

interface ResearchThinkingProps {
  steps: SSEThinking[]
  isStreaming: boolean
}

export function ResearchThinking({ steps, isStreaming }: ResearchThinkingProps) {
  const [manualOpen, setManualOpen] = useState(true)
  const open = isStreaming ? true : manualOpen

  if (steps.length === 0) return null

  return (
    <Reasoning open={open} onOpenChange={setManualOpen} isStreaming={isStreaming}>
      <ReasoningTrigger className="text-xs text-muted-foreground hover:text-foreground font-medium transition-colors">
        {isStreaming ? (
          <span className="flex items-center gap-1">
            思维链生成中
            <span className="inline-flex gap-0.5">
              <span className="animate-bounce [animation-delay:0ms]">.</span>
              <span className="animate-bounce [animation-delay:150ms]">.</span>
              <span className="animate-bounce [animation-delay:300ms]">.</span>
            </span>
          </span>
        ) : (
          `已记录 ${steps.length} 条推理步骤`
        )}
      </ReasoningTrigger>
      <ReasoningContent
        className="mt-2 pl-3 border-l border-border flex flex-col gap-3"
        contentClassName="text-xs leading-relaxed whitespace-pre-wrap font-mono opacity-75"
      >
        {steps.map((step, idx) => {
          const stepStreaming = isStreaming && step.done !== true && idx === steps.length - 1
          const prefixMap: Record<string, string> = {
            chem_agent: '[系统规划] ',
            tools_executor: '[工具执行] ',
            llm_reasoning: '[模型推理] ',
          }
          const prefixText = prefixMap[step.source || 'llm_reasoning'] || ''

          return (
            <div key={idx} className="relative">
              <span className="font-semibold text-primary/80 mr-1">{prefixText}</span>
              {step.text}
              {stepStreaming && (
                <span className="inline-block w-[2px] h-[1em] ml-0.5 bg-current align-middle animate-pulse" />
              )}
            </div>
          )
        })}
      </ReasoningContent>
    </Reasoning>
  )
}
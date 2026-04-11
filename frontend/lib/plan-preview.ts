export interface PlanPreviewStage {
  id: string
  title: string
  intent: string
}

export interface PlanPreview {
  goal: string
  stages: PlanPreviewStage[]
}

function normalizeInlineMarkdown(text: string): string {
  return text
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/\[(.*?)\]\((.*?)\)/g, '$1')
    .trim()
}

function extractGoal(markdown: string): string {
  const goalMatch = markdown.match(/#\s*总体生化目标\s*([\s\S]*?)(?:\n#\s|$)/)
  if (!goalMatch) return ''

  return normalizeInlineMarkdown(
    goalMatch[1]
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .join(' '),
  )
}

function extractIntent(section: string): string {
  const intentMatch = section.match(/^[\-*]\s*\*\*动作意图\*\*\s*[:：]\s*(.+)$/m)
  if (intentMatch) {
    return normalizeInlineMarkdown(intentMatch[1])
  }

  const firstContentLine = section
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith('## '))

  return firstContentLine ? normalizeInlineMarkdown(firstContentLine.replace(/^[\-*]\s*/, '')) : ''
}

export function parsePlanPreview(markdown: string): PlanPreview {
  const goal = extractGoal(markdown)
  const stages: PlanPreviewStage[] = []
  const stageRegex = /^##\s*阶段\s*(\d+)\s*[:：]\s*(.+)$/gm
  const matches = Array.from(markdown.matchAll(stageRegex))

  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index]
    const headingIndex = match.index ?? 0
    const nextIndex = matches[index + 1]?.index ?? markdown.length
    const section = markdown.slice(headingIndex, nextIndex)
    const stageNumber = match[1]
    const title = normalizeInlineMarkdown(match[2])
    const intent = extractIntent(section)

    stages.push({
      id: `stage-${stageNumber}`,
      title: title || `阶段 ${stageNumber}`,
      intent,
    })
  }

  return { goal, stages }
}
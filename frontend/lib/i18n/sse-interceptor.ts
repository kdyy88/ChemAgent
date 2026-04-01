/**
 * SSE Event Interceptor — real-time i18n mapping for LangGraph agent events.
 *
 * When the backend pushes events like `node_start`, `tool_start`, or status
 * strings, these arrive as English keys (node names, tool names) or pre-baked
 * Chinese strings.  This interceptor translates them to the user's active
 * language using the `agent` and `chemistry` namespaces.
 *
 * Design: Pure functions only — no React hooks, no side-effects.
 * They read from the i18next singleton so they can be called from Zustand
 * actions, SSEClient handlers, or any non-React context.
 *
 * Usage:
 *   import { translateNodeLabel, translateToolLabel, translateStatusLabel } from '@/lib/i18n/sse-interceptor'
 *
 *   // In sseStore setActiveNode():
 *   statusLabel: translateNodeLabel(node)
 *
 *   // In sse-client tool_start handler:
 *   const display = translateToolLabel(ev.tool)
 *
 *   // In sseStore updateTasks():
 *   statusLabel: translateStatusLabel('task_running', { id: activeTask.id })
 */

import i18next from '@/lib/i18n/client'
import type {} from '@/lib/i18n/types'

// Pre-load namespaces needed by Zustand/SSE handlers so t() works before
// any React component mounts and triggers useTranslation().
i18next.loadNamespaces(['agent'])

// ── Node label translation ────────────────────────────────────────────────────

/**
 * Map a LangGraph node name to a localized status label.
 * Falls back to the `agent:node.unknown` template if the node isn't listed.
 *
 * @example
 *   translateNodeLabel('chem_agent')  // zh: "🧠 智能体推理中…"  en: "🧠 Agent reasoning…"
 */
export function translateNodeLabel(node: string): string {
  const result = (i18next.t as (k: string, opts: object) => unknown)(
    `agent:node.${node}`,
    { defaultValue: '' },
  ) as string
  if (result) return result
  return i18next.t('agent:node.unknown', { node })
}

// ── Tool label translation ────────────────────────────────────────────────────

/**
 * Map a backend tool name (snake_case) to a localized display label.
 * Tries `chemistry:tool.<name>` first, then `agent:node.<name>` as fallback.
 *
 * @example
 *   translateToolLabel('validate_smiles')  // zh: "校验 SMILES"  en: "Validate SMILES"
 *   translateToolLabel('tool_pubchem_lookup')  // zh: "查询 PubChem"
 */
export function translateToolLabel(toolName: string): string {
  const lookupKey = toolName.startsWith('tool_') ? toolName.slice(5) : toolName

  const chemResult = (i18next.t as (k: string, opts: object) => unknown)(
    `chemistry:tool.${lookupKey}`,
    { defaultValue: '' },
  ) as string
  if (chemResult) return chemResult

  return lookupKey.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// ── Status label translation ──────────────────────────────────────────────────

type StatusKey = keyof (typeof import('../../public/locales/en/agent.json'))['status']

/**
 * Translate a status key from the `agent:status` namespace with interpolation.
 *
 * @example
 *   translateStatusLabel('tool_running')           // "🛠️ Executing tool…"
 *   translateStatusLabel('task_running', { id: 3 }) // "📋 Executing task 3"
 *   translateStatusLabel('shadow_error')            // "⚠️ Correcting structure issue…"
 */
export function translateStatusLabel(key: StatusKey, vars?: Record<string, unknown>): string {
  return i18next.t(`agent:status.${key}`, vars as Record<string, string> | undefined)
}

// ── Error message translation ────────────────────────────────────────────────

/**
 * Build a localized stream error message from the backend error string.
 *
 * @example
 *   translateStreamError('RDKit error: invalid SMILES')
 *   // zh: "\n\n> ❌ **错误**: RDKit error: invalid SMILES"
 */
export function translateStreamError(error: string): string {
  const key = 'agent:error.stream_error'
  const result = i18next.t(key, { error })
  // If namespace not yet loaded, i18next returns the key — use inline fallback
  if (result === key || result.includes('error.stream_error')) {
    return `\n\n> ❌ **错误**: ${error}`
  }
  return result
}

/**
 * Build a localized connection-lost error message.
 *
 * @example
 *   translateConnectionError('network timeout')
 *   // zh: "❌ 连接中断: network timeout"
 */
export function translateConnectionError(message: string): string {
  const key = 'agent:error.connection_lost'
  const result = i18next.t(key, { message })
  // If namespace not yet loaded, i18next returns the key — use inline fallback
  if (result === key || result.includes('error.connection_lost')) {
    return `❌ 连接中断: ${message}`
  }
  return result
}

// ── Thinking text translation ────────────────────────────────────────────────

/**
 * Translate a well-known backend reasoning message key to the user's locale.
 * The backend emits fixed Chinese strings (e.g. from _NODE_REASONING_MESSAGES).
 * This function maps them to the `agent:reasoning` namespace so English users
 * see localized text.
 *
 * The mapping is keyed on the trimmed Chinese source string.
 */
const ZH_REASONING_MAP: Record<string, keyof (typeof import('../../public/locales/en/agent.json'))['reasoning']> = {
  '正在快速判断这次请求是否需要显式任务规划...': 'task_router_start',
  '复杂度判断完成。': 'task_router_end',
  '检测到复杂任务，正在生成可执行任务清单...': 'planner_start',
  '任务清单已生成，准备进入执行阶段。': 'planner_end',
  '进入智能体大脑，正在评估当前信息并规划下一步行动...': 'agent_start',
  '智能体本轮思考完毕。': 'agent_end',
  '准备转入工具执行流水线...': 'executor_start',
  '工具调用链执行完毕，正在将实验数据交回给智能体大脑。': 'executor_end',
}

/**
 * If `text` is one of the known backend reasoning messages (currently emitted
 * as hardcoded Chinese strings), returns the localized equivalent.
 * Otherwise returns the original text unchanged.
 */
export function translateReasoningText(text: string): string {
  const reasoningKey = ZH_REASONING_MAP[text.trim()]
  if (!reasoningKey) return text
  return i18next.t(`agent:reasoning.${reasoningKey}`)
}

/**
 * Returns true if `text` matches a known low-value reasoning message in ANY
 * supported language, so `sseStore` can filter them regardless of locale.
 */
const ZH_LOW_VALUE_SET = new Set(Object.keys(ZH_REASONING_MAP))

export function isLowValueReasoningText(text: string): boolean {
  const trimmed = text.trim()
  if (ZH_LOW_VALUE_SET.has(trimmed)) return true
  // Also check already-translated English equivalents
  for (const key of Object.values(ZH_REASONING_MAP)) {
    const enText = i18next.t(`agent:reasoning.${key}`, { lng: 'en' })
    if (trimmed === enText.trim()) return true
  }
  return false
}

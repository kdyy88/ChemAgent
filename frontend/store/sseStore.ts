/**
 * sseStore — global Zustand store for the LangGraph SSE chat.
 *
 * This store is intentionally state-focused. The SSE transport and its
 * runtime caches live in services/sse-client.ts; the store only describes how
 * events mutate UI state.
 */

import { create } from 'zustand'
import type {
  ChatModelOption,
  PendingPlanContext,
  SSEArtifactEvent,
  SSEPendingApproval,
  SSEPendingInterrupt,
  SSESendMessageOptions,
  SSEShadowError,
  SSETaskItem,
  SSEThinking,
  SSEUsage,
  SSEUsageSnapshot,
  SSETurn,
} from '@/lib/sse-types'
import { fetchPlanDocument } from '@/lib/artifact-api'
import { fetchAvailableModels } from '@/lib/chat-api'
import { sseClient } from '@/services/sse-client'
import { useWorkspaceStore } from '@/store/workspaceStore'
import {
  translateNodeLabel,
  translateStatusLabel,
  translateConnectionError,
  isLowValueReasoningText,
  translateReasoningText,
} from '@/lib/i18n/sse-interceptor'

function makeApprovalStatusLabel(approval: SSEPendingApproval): string {
  return approval.kind === 'plan' ? '⏸️ 等待计划审批' : '⏸️ 等待工具审批'
}

const WORKSPACE_SMILES_KEYS = [
  'cleaned_smiles',
  'canonical_smiles',
  'scaffold_smiles',
  'smiles',
] as const

function normalizeThinkingText(text: string): string {
  return text
    .replace(/[▁]/g, ' ')
    .replace(/[Ġ]/g, ' ')
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
}

function shouldIgnoreThinking(entry: SSEThinking, text: string): boolean {
  if (!text) return true
  if (entry.importance === 'low') return true
  if (isLowValueReasoningText(text)) return true
  if (text.includes('本轮未收到可展示的模型 reasoning 摘要')) return true
  if (text.includes('No model reasoning summary received')) return true
  return false
}

function updateWorkspaceFromPayload(payload: Record<string, unknown>) {
  const nextSmiles = WORKSPACE_SMILES_KEYS.find((key) => typeof payload[key] === 'string')
  const nextName = typeof payload.name === 'string' ? payload.name : undefined
  const workspace = useWorkspaceStore.getState()

  if (nextSmiles) workspace.setSmiles(payload[nextSmiles] as string)
  if (nextName) workspace.setName(nextName)
}

function appendThinkingStep(steps: SSEThinking[], entry: SSEThinking): SSEThinking[] {
  // Translate any known backend reasoning strings to the user's active locale
  const text = normalizeThinkingText(translateReasoningText(entry.text))
  if (shouldIgnoreThinking(entry, text)) return steps

  const next = [...steps]
  const last = next[next.length - 1]
  if (
    last &&
    last.done !== true &&
    entry.done === false &&
    last.source === entry.source &&
    last.iteration === entry.iteration
  ) {
    next[next.length - 1] = {
      ...last,
      text: `${last.text}${text}`,
      done: entry.done,
      category: entry.category ?? last.category,
      importance: entry.importance ?? last.importance,
      group_key: entry.group_key ?? last.group_key,
    }
    return next
  }

  if (last && last.source === entry.source && last.iteration === entry.iteration) {
    const lastTrimmed = last.text.trim()
    const textTrimmed = text.trim()
    if (
      lastTrimmed === textTrimmed ||
      textTrimmed.startsWith(lastTrimmed) ||
      lastTrimmed.startsWith(textTrimmed)
    ) {
      next[next.length - 1] = {
        ...last,
        text: text.length >= last.text.length ? text : last.text,
        done: entry.done,
        category: entry.category ?? last.category,
        importance: entry.importance ?? last.importance,
        group_key: entry.group_key ?? last.group_key,
      }
      return next
    }
  }

  next.push({ ...entry, text })
  return next
}

function modeToChineseLabel(mode: unknown): string {
  const value = String(mode || '').trim().toLowerCase()
  if (value === 'explore') return '调研'
  if (value === 'plan') return '规划'
  if (value === 'general') return '执行'
  if (value === 'custom') return '自定义'
  return '任务'
}

function summarizeSubAgentCompletion(output: Record<string, unknown>): string {
  const completion = typeof output.completion === 'object' && output.completion !== null
    ? output.completion as Record<string, unknown>
    : null
  const ref = typeof output.scratchpad_report_ref === 'object' && output.scratchpad_report_ref !== null
    ? output.scratchpad_report_ref as Record<string, unknown>
    : null
  const summary = [
    typeof completion?.summary === 'string' ? completion.summary : '',
    typeof output.summary === 'string' ? output.summary : '',
    typeof output.response === 'string' ? output.response : '',
    typeof output.result === 'string' ? output.result : '',
    typeof ref?.summary === 'string' ? ref.summary : '',
  ].find((value) => value.trim().length > 0)?.trim()

  const prefix = `子智能体${modeToChineseLabel(output.mode)}完成`
  return summary ? `${prefix}：${summary}` : `${prefix}，结果已返回主流程。`
}

function createTurn(turnId: string, message: string, tasks: SSETaskItem[]): SSETurn {
  return {
    turnId,
    modelId: null,
    userMessage: message,
    assistantText: '',
    isStreaming: true,
    activeNode: null,
    toolCalls: [],
    artifacts: [],
    tasks,
    shadowErrors: [],
    statusLabel: translateStatusLabel('reasoning'),
    pendingInterrupt: undefined,
    pendingApproval: undefined,
    thinkingSteps: [],
    usage: undefined,
    planDraftText: '',
  }
}

function createUsageSnapshot(usage: SSEUsage): SSEUsageSnapshot {
  return {
    node: usage.node,
    model: usage.model ?? null,
    input_tokens: usage.input_tokens,
    output_tokens: usage.output_tokens,
    total_tokens: usage.total_tokens,
  }
}

function createEmptyUsageTotals() {
  return {
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    event_count: 0,
    last_model: null as string | null,
  }
}

export interface SseState {
  turns: SSETurn[]
  isStreaming: boolean
  availableModels: ChatModelOption[]
  modelsStatus: 'idle' | 'loading' | 'ready' | 'error'
  modelsError: string | null
  selectedModelId: string | null
  sessionUsage: {
    input_tokens: number
    output_tokens: number
    total_tokens: number
    event_count: number
    last_model: string | null
  }
  clearTurns: () => void
  loadAvailableModels: () => Promise<void>
  selectModel: (modelId: string) => void
  sendMessage: (message: string, options?: SSESendMessageOptions) => Promise<void>
  startTurn: (turnId: string, message: string, tasks: SSETaskItem[], modelId?: string | null) => void
  appendAssistantText: (text: string) => void
  replaceAssistantText: (text: string) => void
  setActiveNode: (node: string) => void
  clearActiveNode: (node: string) => void
  addToolCall: (tool: string, input: Record<string, unknown>) => number
  completeToolCall: (index: number, output: Record<string, unknown>) => void
  addArtifact: (artifact: SSEArtifactEvent) => void
  updateTasks: (tasks: SSETaskItem[]) => void
  addShadowError: (error: SSEShadowError) => void
  recordUsage: (usage: SSEUsage) => void
  setPendingInterrupt: (interrupt: SSEPendingInterrupt) => void
  setPendingApproval: (approval: SSEPendingApproval) => void
  approveToolCall: (action: 'approve' | 'reject' | 'modify', args?: Record<string, unknown>, model?: string | null) => Promise<void>
  appendThinking: (thinking: SSEThinking) => void
  appendPlanDraftText: (text: string) => void
  completeStream: () => void
  failStream: (message: string) => void
  handleConnectionError: (message: string) => void
}

export function nodeLabel(node: string): string {
  return translateNodeLabel(node)
}

export const useSseStore = create<SseState>((set, get) => {
  function findLatestPendingPlanApproval(): { approval: Extract<SSEPendingApproval, { kind: 'plan' }>; turnIndex: number } | null {
    const turns = get().turns
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      const approval = turns[index]?.pendingApproval
      if (approval?.kind === 'plan') {
        return { approval, turnIndex: index }
      }
    }
    return null
  }

  async function resolvePendingPlanContext(): Promise<PendingPlanContext | null> {
    const pending = findLatestPendingPlanApproval()
    if (!pending) return null

    const { approval } = pending
    const inlineContent = typeof approval.content === 'string' ? approval.content.trim() : ''
    if (inlineContent) {
      return {
        plan_id: approval.plan_id,
        plan_file_ref: approval.plan_file_ref,
        summary: approval.summary,
        content: inlineContent,
      }
    }

    const sessionId = sseClient.sessionId
    if (!sessionId) return null

    let document
    try {
      document = await fetchPlanDocument(sessionId, approval.plan_id)
    } catch {
      return null
    }
    if (!document || typeof document.content !== 'string' || !document.content.trim()) {
      return null
    }

    return {
      plan_id: document.plan_id,
      plan_file_ref: document.plan_file_ref,
      summary: document.summary,
      content: document.content,
    }
  }

  function findLatestPendingApprovalTurnIndex(): number {
    const turns = get().turns
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      if (turns[index]?.pendingApproval) {
        return index
      }
    }
    return -1
  }

  function updateTurnAt(index: number, updater: (prev: SSETurn) => Partial<SSETurn>) {
    set((state) => {
      if (index < 0 || index >= state.turns.length) return state
      const turns = [...state.turns]
      const current = turns[index]
      turns[index] = { ...current, ...updater(current) }
      return { turns }
    })
  }

  function updateLastTurn(updater: (prev: SSETurn) => Partial<SSETurn>) {
    set((state) => {
      if (state.turns.length === 0) return state
      const turns = [...state.turns]
      const last = turns[turns.length - 1]
      turns[turns.length - 1] = { ...last, ...updater(last) }
      return { turns }
    })
  }

  function stopStreamingTurn(updater?: (prev: SSETurn) => Partial<SSETurn>) {
    updateLastTurn((turn) => ({
      isStreaming: false,
      activeNode: null,
      statusLabel: '',
      ...(updater ? updater(turn) : {}),
    }))
    set({ isStreaming: false })
  }

  return {
    turns: [],
    isStreaming: false,
    availableModels: [],
    modelsStatus: 'idle',
    modelsError: null,
    selectedModelId: null,
    sessionUsage: createEmptyUsageTotals(),

    clearTurns: () => {
      sseClient.clearConversation()
      set((state) => ({
        turns: [],
        isStreaming: false,
        sessionUsage: createEmptyUsageTotals(),
        selectedModelId:
          state.selectedModelId && state.availableModels.some((model) => model.id === state.selectedModelId)
            ? state.selectedModelId
            : state.availableModels.find((model) => model.is_default)?.id ?? state.availableModels[0]?.id ?? null,
      }))
      const workspace = useWorkspaceStore.getState()
      workspace.setSmiles('')
      workspace.setName('')
    },

    loadAvailableModels: async () => {
      if (get().modelsStatus === 'loading') return

      set({ modelsStatus: 'loading', modelsError: null })
      try {
        const response = await fetchAvailableModels()
        set((state) => {
          const fallbackModelId = response.models.find((model) => model.is_default)?.id ?? response.models[0]?.id ?? null
          const selectedModelId =
            state.selectedModelId && response.models.some((model) => model.id === state.selectedModelId)
              ? state.selectedModelId
              : fallbackModelId
          return {
            availableModels: response.models,
            modelsStatus: 'ready',
            modelsError: response.warning ?? null,
            selectedModelId,
          }
        })
      } catch (error) {
        set({
          modelsStatus: 'error',
          modelsError: error instanceof Error ? error.message : String(error),
        })
      }
    },

    selectModel: (modelId) => {
      if (!get().availableModels.some((model) => model.id === modelId)) return
      set({ selectedModelId: modelId })
    },

    sendMessage: async (message, options = {}) => {
      if (get().isStreaming) return

      const selectedModelId = options.model ?? get().selectedModelId ?? null
      const pendingPlanContext = await resolvePendingPlanContext()

      await sseClient.sendMessage({
        message,
        previousTasks: get().turns.at(-1)?.tasks ?? [],
        options: {
          ...options,
          model: selectedModelId,
          pendingPlanContext,
        },
        handlers: {
          startTurn: (turnId, userMessage, tasks) => {
            get().startTurn(turnId, userMessage, tasks, selectedModelId)
          },
          activateNode: (node) => {
            get().setActiveNode(node)
          },
          clearNode: (node) => {
            get().clearActiveNode(node)
          },
          appendAssistantText: (text) => {
            get().appendAssistantText(text)
          },
          addToolCall: (tool, input) => {
            return get().addToolCall(tool, input)
          },
          completeToolCall: (index, output) => {
            updateWorkspaceFromPayload(output)
            get().completeToolCall(index, output)
          },
          addArtifact: (artifact) => {
            if ('smiles' in artifact && typeof artifact.smiles === 'string') {
              updateWorkspaceFromPayload({ smiles: artifact.smiles })
            }
            get().addArtifact(artifact)
          },
          updateTasks: (tasks) => {
            get().updateTasks(tasks)
          },
          addShadowError: (error) => {
            get().addShadowError(error)
          },
          appendThinking: (thinking) => {
            get().appendThinking(thinking)
          },
          appendPlanDraftText: (text) => {
            get().appendPlanDraftText(text)
          },
          recordUsage: (usage) => {
            get().recordUsage(usage)
          },
          setPendingInterrupt: (interrupt) => {
            get().setPendingInterrupt(interrupt)
          },
          setPendingApproval: (approval) => {
            get().setPendingApproval(approval)
          },
          completeTurn: () => {
            get().completeStream()
          },
          failTurn: (errorMessage) => {
            get().failStream(errorMessage)
          },
          handleHttpError: (status, text) => {
            get().replaceAssistantText(`❌ HTTP ${status}: ${text}`)
          },
          handleConnectionError: (errorMessage) => {
            get().handleConnectionError(errorMessage)
          },
        },
      })
    },

    startTurn: (turnId, message, tasks, modelId) => {
      set((state) => ({
        turns: [...state.turns, { ...createTurn(turnId, message, tasks), modelId: modelId ?? state.selectedModelId }],
        isStreaming: true,
      }))
    },

    appendAssistantText: (text) => {
      updateLastTurn((turn) => ({
        assistantText: turn.assistantText + text,
      }))
    },

    replaceAssistantText: (text) => {
      stopStreamingTurn(() => ({
        assistantText: text,
      }))
    },

    setActiveNode: (node) => {
      updateLastTurn(() => ({
        activeNode: node,
        statusLabel: nodeLabel(node),
      }))
    },

    clearActiveNode: (node) => {
      updateLastTurn((turn) => ({
        activeNode: turn.activeNode === node ? null : turn.activeNode,
        statusLabel: turn.activeNode === node ? '' : turn.statusLabel,
      }))
    },

    addToolCall: (tool, input) => {
      const index = get().turns.at(-1)?.toolCalls.length ?? 0
      updateLastTurn((turn) => ({
        toolCalls: [...turn.toolCalls, { tool, input, output: undefined, done: false }],
        statusLabel: translateStatusLabel('tool_running'),
      }))
      return index
    },

    completeToolCall: (index, output) => {
      updateLastTurn((turn) => {
        if (index < 0 || index >= turn.toolCalls.length)
          return { statusLabel: translateStatusLabel('integrating_results') }

        const toolCalls = [...turn.toolCalls]
        const currentCall = toolCalls[index]
        toolCalls[index] = {
          ...currentCall,
          output,
          done: true,
        }

        const thinkingSteps =
          currentCall?.tool === 'tool_run_sub_agent'
            ? appendThinkingStep(turn.thinkingSteps, {
                type: 'thinking',
                text: summarizeSubAgentCompletion(output),
                iteration: 0,
                done: true,
                source: `sub_agent_report:${index}`,
                category: 'tool',
                importance: 'high',
                group_key: `sub_agent_report:${index}`,
                session_id: '',
                turn_id: turn.turnId,
              })
            : turn.thinkingSteps

        return {
          toolCalls,
          thinkingSteps,
          statusLabel: translateStatusLabel('integrating_results'),
        }
      })
    },

    addArtifact: (artifact) => {
      updateLastTurn((turn) => ({
        artifacts: [...turn.artifacts, artifact],
      }))
    },

    updateTasks: (tasks) => {
      const activeTask = tasks.find((task) => task.status === 'in_progress')
      updateLastTurn(() => ({
        tasks,
        statusLabel: activeTask
          ? translateStatusLabel('task_running', { id: activeTask.id })
          : translateStatusLabel('task_list_updated'),
      }))
    },

    addShadowError: (error) => {
      updateLastTurn((turn) => ({
        shadowErrors: [...turn.shadowErrors, error],
        statusLabel: translateStatusLabel('shadow_error'),
      }))
    },

    recordUsage: (usage) => {
      updateLastTurn(() => ({
        usage: createUsageSnapshot(usage),
      }))
      set((state) => ({
        sessionUsage: {
          input_tokens: state.sessionUsage.input_tokens + usage.input_tokens,
          output_tokens: state.sessionUsage.output_tokens + usage.output_tokens,
          total_tokens: state.sessionUsage.total_tokens + usage.total_tokens,
          event_count: state.sessionUsage.event_count + 1,
          last_model: usage.model ?? state.sessionUsage.last_model,
        },
      }))
    },

    setPendingInterrupt: (interrupt) => {
      stopStreamingTurn((turn) => ({
        statusLabel: translateStatusLabel('awaiting_reply'),
        pendingInterrupt: interrupt,
        thinkingSteps: appendThinkingStep(turn.thinkingSteps, {
          type: 'thinking',
          text: `${translateStatusLabel('awaiting_reply').replace(/^🙋 /, '')} ${interrupt.question}`,
          iteration: 0,
          done: true,
          source: 'chem_agent',
          session_id: '',
          turn_id: turn.turnId,
        }),
      }))
    },

    setPendingApproval: (approval) => {
      stopStreamingTurn((turn) => ({
        statusLabel: makeApprovalStatusLabel(approval),
        pendingApproval: approval,
        // Clear plan draft text — the ApprovalCard takes over rendering the plan
        planDraftText: turn.planDraftText ? '' : turn.planDraftText,
      }))
    },

    approveToolCall: async (action, args, model) => {
      if (get().isStreaming) return
      const sessionId = sseClient.sessionId
      if (!sessionId) return

      const turnId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2) + Date.now().toString(36)

      const pendingApprovalTurnIndex = findLatestPendingApprovalTurnIndex()
      if (pendingApprovalTurnIndex < 0) return
      const pendingApproval = get().turns[pendingApprovalTurnIndex]?.pendingApproval
      if (!pendingApproval) return

      const approvalTarget = pendingApproval.kind === 'plan'
        ? `plan ${pendingApproval.plan_id.slice(0, 8)}`
        : pendingApproval.tool_name.replace('tool_', '')
      const actionLabel = action === 'approve' ? '✅ 批准' : action === 'reject' ? '❌ 拒绝' : '✏️ 修改并保存'
      const approvalLabel = `${actionLabel}: ${approvalTarget}`

      // Clear the pendingApproval badge on the last turn before starting the new one
      updateTurnAt(pendingApprovalTurnIndex, () => ({ pendingApproval: undefined }))

      const handlers = {
        startTurn: (tId: string, message: string, tasks: SSETaskItem[]) => {
          get().startTurn(tId, message, tasks)
        },
        activateNode: (node: string) => { get().setActiveNode(node) },
        clearNode: (node: string) => { get().clearActiveNode(node) },
        appendAssistantText: (text: string) => { get().appendAssistantText(text) },
        addToolCall: (tool: string, input: Record<string, unknown>) => get().addToolCall(tool, input),
        completeToolCall: (index: number, output: Record<string, unknown>) => {
          updateWorkspaceFromPayload(output)
          get().completeToolCall(index, output)
        },
        addArtifact: (artifact: SSEArtifactEvent) => {
          if ('smiles' in artifact && typeof artifact.smiles === 'string') {
            updateWorkspaceFromPayload({ smiles: artifact.smiles })
          }
          get().addArtifact(artifact)
        },
        updateTasks: (tasks: SSETaskItem[]) => { get().updateTasks(tasks) },
        addShadowError: (error: SSEShadowError) => { get().addShadowError(error) },
        appendThinking: (thinking: SSEThinking) => { get().appendThinking(thinking) },
        appendPlanDraftText: (text: string) => { get().appendPlanDraftText(text) },
        recordUsage: (usage: SSEUsage) => { get().recordUsage(usage) },
        setPendingInterrupt: (interrupt: SSEPendingInterrupt) => { get().setPendingInterrupt(interrupt) },
        setPendingApproval: (approval: SSEPendingApproval) => { get().setPendingApproval(approval) },
        completeTurn: () => { get().completeStream() },
        failTurn: (message: string) => { get().failStream(message) },
        handleHttpError: (status: number, text: string) => {
          get().replaceAssistantText(`❌ HTTP ${status}: ${text}`)
        },
        handleConnectionError: (message: string) => { get().handleConnectionError(message) },
      }

      await sseClient.sendApproval({
        sessionId,
        turnId,
        approvalLabel,
        action,
        args,
        planId: pendingApproval.kind === 'plan' ? pendingApproval.plan_id : undefined,
        model: model ?? null,
        handlers,
      })
    },

    appendThinking: (thinking) => {
      updateLastTurn((turn) => ({
        thinkingSteps: appendThinkingStep(turn.thinkingSteps, thinking),
      }))
    },

    appendPlanDraftText: (text) => {
      updateLastTurn((turn) => ({
        planDraftText: (turn.planDraftText ?? '') + text,
      }))
    },

    completeStream: () => {
      stopStreamingTurn()
    },

    failStream: (message) => {
      stopStreamingTurn((turn) => ({
        assistantText: message ? `${turn.assistantText}${message}` : turn.assistantText,
      }))
    },

    handleConnectionError: (message) => {
      stopStreamingTurn(() => ({
        assistantText: translateConnectionError(message),
      }))
    },
  }
})

/**
 * sseStore — global Zustand store for the LangGraph SSE chat.
 *
 * This store is intentionally state-focused. The SSE transport and its
 * runtime caches live in services/sse-client.ts; the store only describes how
 * events mutate UI state.
 */

import { create } from 'zustand'
import type {
  SSEArtifactEvent,
  SSEPendingApproval,
  SSEPendingInterrupt,
  SSESendMessageOptions,
  SSEShadowError,
  SSETaskItem,
  SSEThinking,
  SSETurn,
} from '@/lib/sse-types'
import { sseClient } from '@/services/sse-client'
import { useWorkspaceStore } from '@/store/workspaceStore'
import {
  translateNodeLabel,
  translateStatusLabel,
  translateConnectionError,
  isLowValueReasoningText,
  translateReasoningText,
} from '@/lib/i18n/sse-interceptor'

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

function createTurn(turnId: string, message: string, tasks: SSETaskItem[]): SSETurn {
  return {
    turnId,
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
  }
}

export interface SseState {
  turns: SSETurn[]
  isStreaming: boolean
  clearTurns: () => void
  sendMessage: (message: string, options?: SSESendMessageOptions) => Promise<void>
  startTurn: (turnId: string, message: string, tasks: SSETaskItem[]) => void
  appendAssistantText: (text: string) => void
  replaceAssistantText: (text: string) => void
  setActiveNode: (node: string) => void
  clearActiveNode: (node: string) => void
  addToolCall: (tool: string, input: Record<string, unknown>) => number
  completeToolCall: (index: number, output: Record<string, unknown>) => void
  addArtifact: (artifact: SSEArtifactEvent) => void
  updateTasks: (tasks: SSETaskItem[]) => void
  addShadowError: (error: SSEShadowError) => void
  setPendingInterrupt: (interrupt: SSEPendingInterrupt) => void
  setPendingApproval: (approval: SSEPendingApproval) => void
  approveToolCall: (action: 'approve' | 'reject' | 'modify', args?: Record<string, unknown>) => Promise<void>
  appendThinking: (thinking: SSEThinking) => void
  completeStream: () => void
  failStream: (message: string) => void
  handleConnectionError: (message: string) => void
}

export function nodeLabel(node: string): string {
  return translateNodeLabel(node)
}

export const useSseStore = create<SseState>((set, get) => {
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

    clearTurns: () => {
      sseClient.clearConversation()
      set({ turns: [], isStreaming: false })
      const workspace = useWorkspaceStore.getState()
      workspace.setSmiles('')
      workspace.setName('')
    },

    sendMessage: async (message, options = {}) => {
      if (get().isStreaming) return

      await sseClient.sendMessage({
        message,
        previousTasks: get().turns.at(-1)?.tasks ?? [],
        options,
        handlers: {
          startTurn: (turnId, userMessage, tasks) => {
            get().startTurn(turnId, userMessage, tasks)
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

    startTurn: (turnId, message, tasks) => {
      set((state) => ({
        turns: [...state.turns, createTurn(turnId, message, tasks)],
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
        toolCalls[index] = {
          ...toolCalls[index],
          output,
          done: true,
        }

        return {
          toolCalls,
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
      stopStreamingTurn(() => ({
        statusLabel: '⏸️ 等待审批',
        pendingApproval: approval,
      }))
    },

    approveToolCall: async (action, args) => {
      if (get().isStreaming) return
      const sessionId = sseClient.sessionId
      if (!sessionId) return

      const turnId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2) + Date.now().toString(36)

      const pendingApproval = get().turns.at(-1)?.pendingApproval
      const toolNameLabel = pendingApproval?.tool_name?.replace('tool_', '') ?? ''
      const actionLabel = action === 'approve' ? '✅ 批准' : action === 'reject' ? '❌ 拒绝' : '✏️ 修改并批准'
      const approvalLabel = `${actionLabel}: ${toolNameLabel}`

      // Clear the pendingApproval badge on the last turn before starting the new one
      updateLastTurn(() => ({ pendingApproval: undefined }))

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
        setPendingInterrupt: (interrupt: SSEPendingInterrupt) => { get().setPendingInterrupt(interrupt) },
        setPendingApproval: (approval: SSEPendingApproval) => { get().setPendingApproval(approval) },
        completeTurn: () => { get().completeStream() },
        failTurn: (message: string) => { get().failStream(message) },
        handleHttpError: (status: number, text: string) => {
          get().replaceAssistantText(`❌ HTTP ${status}: ${text}`)
        },
        handleConnectionError: (message: string) => { get().handleConnectionError(message) },
      }

      await sseClient.sendApproval({ sessionId, turnId, approvalLabel, action, args, handlers })
    },

    appendThinking: (thinking) => {
      updateLastTurn((turn) => ({
        thinkingSteps: appendThinkingStep(turn.thinkingSteps, thinking),
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

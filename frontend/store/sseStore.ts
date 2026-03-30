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
  SSEPendingInterrupt,
  SSESendMessageOptions,
  SSEShadowError,
  SSETaskItem,
  SSEThinking,
  SSETurn,
} from '@/lib/sse-types'
import { sseClient } from '@/services/sse-client'
import { useWorkspaceStore } from '@/store/workspaceStore'

const WORKSPACE_SMILES_KEYS = [
  'cleaned_smiles',
  'canonical_smiles',
  'scaffold_smiles',
  'smiles',
] as const

const NODE_LABELS: Record<string, string> = {
  task_router: '🧭 正在判断任务复杂度…',
  planner_node: '🗂️ 正在生成任务清单…',
  chem_agent: '🧠 智能体推理中…',
  tools_executor: '🛠️ 工具执行中…',
}

function normalizeThinkingText(text: string): string {
  return text
    .replace(/[▁]/g, ' ')
    .replace(/[Ġ]/g, ' ')
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
}

function updateWorkspaceFromPayload(payload: Record<string, unknown>) {
  const nextSmiles = WORKSPACE_SMILES_KEYS.find((key) => typeof payload[key] === 'string')
  const nextName = typeof payload.name === 'string' ? payload.name : undefined
  const workspace = useWorkspaceStore.getState()

  if (nextSmiles) workspace.setSmiles(payload[nextSmiles] as string)
  if (nextName) workspace.setName(nextName)
}

function appendThinkingStep(steps: SSEThinking[], entry: SSEThinking): SSEThinking[] {
  const text = normalizeThinkingText(entry.text)
  if (!text) return steps

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
    statusLabel: '🧠 智能体推理中…',
    pendingInterrupt: undefined,
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
  appendThinking: (thinking: SSEThinking) => void
  completeStream: () => void
  failStream: (message: string) => void
  handleConnectionError: (message: string) => void
}

export function nodeLabel(node: string): string {
  return NODE_LABELS[node] ?? `${node} 执行中…`
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
        statusLabel: '🛠️ 工具执行中…',
      }))
      return index
    },

    completeToolCall: (index, output) => {
      updateLastTurn((turn) => {
        if (index < 0 || index >= turn.toolCalls.length) return { statusLabel: '🧠 正在整合工具结果…' }

        const toolCalls = [...turn.toolCalls]
        toolCalls[index] = {
          ...toolCalls[index],
          output,
          done: true,
        }

        return {
          toolCalls,
          statusLabel: '🧠 正在整合工具结果…',
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
        statusLabel: activeTask ? `📋 正在执行任务 ${activeTask.id}` : '📋 任务清单已更新',
      }))
    },

    addShadowError: (error) => {
      updateLastTurn((turn) => ({
        shadowErrors: [...turn.shadowErrors, error],
        statusLabel: '⚠️ 正在修正结构问题…',
      }))
    },

    setPendingInterrupt: (interrupt) => {
      stopStreamingTurn((turn) => ({
        statusLabel: '🙋 等待您的回复…',
        pendingInterrupt: interrupt,
        thinkingSteps: appendThinkingStep(turn.thinkingSteps, {
          type: 'thinking',
          text: `需要用户澄清：${interrupt.question}`,
          iteration: 0,
          done: true,
          source: 'chem_agent',
          session_id: '',
          turn_id: turn.turnId,
        }),
      }))
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
        assistantText: `❌ 连接中断: ${message}`,
      }))
    },
  }
})

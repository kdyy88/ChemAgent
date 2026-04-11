'use client'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const loadAvailableModelsMock = vi.fn()

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('@/lib/i18n/client', () => ({}))

vi.mock('@/store/workspaceStore', () => ({
  useWorkspaceStore: (selector?: (state: {
    currentSmiles: string
  }) => unknown) => {
    const state = { currentSmiles: '' }
    return selector ? selector(state) : state
  },
}))

vi.mock('@/store/sseStore', () => ({
  useSseStore: (selector?: (state: {
    turns: never[]
    sessionUsage: { total_tokens: number }
    availableModels: never[]
    modelsStatus: string
    modelsError: string | null
    selectedModelId: string | null
    selectModel: (modelId: string) => void
    loadAvailableModels: () => Promise<void>
  }) => unknown) => {
    const state = {
      turns: [],
      sessionUsage: { total_tokens: 0 },
      availableModels: [],
      modelsStatus: 'idle',
      modelsError: null,
      selectedModelId: null,
      selectModel: () => {},
      loadAvailableModels: loadAvailableModelsMock,
    }
    return selector ? selector(state) : state
  },
}))

import { SSEChatInput } from '../SSEChatInput'

describe('SSEChatInput', () => {
  beforeEach(() => {
    loadAvailableModelsMock.mockReset()
    loadAvailableModelsMock.mockResolvedValue(undefined)
  })

  it('submits exactly once when pressing Enter', async () => {
    const user = userEvent.setup()
    const sendMessage = vi.fn().mockResolvedValue(undefined)

    render(
      <SSEChatInput
        isStreaming={false}
        sendMessage={sendMessage}
      />,
    )

    const textbox = screen.getByRole('textbox')
    await user.type(textbox, '删除关键依赖与数据缺口段落{enter}')

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledTimes(1)
    })
    expect(sendMessage).toHaveBeenCalledWith(
      '删除关键依赖与数据缺口段落',
      expect.objectContaining({ mode: 'general' }),
    )
  })
})
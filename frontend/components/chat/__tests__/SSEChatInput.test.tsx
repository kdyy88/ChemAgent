import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SSEChatInput } from '../SSEChatInput'
import { useWorkspaceStore } from '@/store/workspaceStore'

describe('SSEChatInput', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      navMode: 'business',
      activeFunctionId: null,
      currentSmiles: '',
      currentName: '',
    })
  })

  it('renders with placeholder text when no function is active', () => {
    const mockSendMessage = vi.fn()
    const mockClearTurns = vi.fn()

    render(
      <SSEChatInput
        isStreaming={false}
        sendMessage={mockSendMessage}
        clearTurns={mockClearTurns}
      />,
    )

    expect(screen.getByPlaceholderText('Ask about any chemical compound…')).toBeInTheDocument()
  })

  it('adds SMILES tag when "Add current SMILES" button is clicked', async () => {
    const user = userEvent.setup()
    useWorkspaceStore.setState({
      currentSmiles: 'CCO',
      currentName: 'Ethanol',
    })

    const mockSendMessage = vi.fn()
    const mockClearTurns = vi.fn()

    render(
      <SSEChatInput
        isStreaming={false}
        sendMessage={mockSendMessage}
        clearTurns={mockClearTurns}
      />,
    )

    const addButton = screen.getByRole('button', { name: 'Add current SMILES' })
    await user.click(addButton)

    // The tag should now be visible
    expect(screen.getByTitle('CCO')).toBeInTheDocument()
    expect(screen.getByText('🧪 CCO')).toBeInTheDocument()
  })

  it('removes SMILES tag when X button is clicked', async () => {
    const user = userEvent.setup()
    useWorkspaceStore.setState({
      currentSmiles: 'CCO',
    })

    const mockSendMessage = vi.fn()
    const mockClearTurns = vi.fn()

    render(
      <SSEChatInput
        isStreaming={false}
        sendMessage={mockSendMessage}
        clearTurns={mockClearTurns}
      />,
    )

    // Add the tag
    const addButton = screen.getByRole('button', { name: 'Add current SMILES' })
    await user.click(addButton)

    expect(screen.getByText('🧪 CCO')).toBeInTheDocument()

    // Remove the tag
    const removeButton = screen.getByRole('button', { name: 'Remove SMILES' })
    await user.click(removeButton)

    expect(screen.queryByText('🧪 CCO')).not.toBeInTheDocument()
  })

  it('truncates long SMILES strings in the tag display', async () => {
    const user = userEvent.setup()
    const longSmiles = 'CCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOCCOccoc'
    useWorkspaceStore.setState({
      currentSmiles: longSmiles,
    })

    const mockSendMessage = vi.fn()
    const mockClearTurns = vi.fn()

    render(
      <SSEChatInput
        isStreaming={false}
        sendMessage={mockSendMessage}
        clearTurns={mockClearTurns}
      />,
    )

    const addButton = screen.getByRole('button', { name: 'Add current SMILES' })
    await user.click(addButton)

    // The full SMILES should be in title attribute
    expect(screen.getByTitle(longSmiles)).toBeInTheDocument()
    // But displayed text should be truncated with ellipsis
    const element = screen.getByText(/🧪/)
    expect(element.textContent).toMatch(/🧪.*…/)
  })

  it('disables "Add SMILES" button when SMILES is already added', async () => {
    const user = userEvent.setup()
    useWorkspaceStore.setState({
      currentSmiles: 'CCO',
    })

    const mockSendMessage = vi.fn()
    const mockClearTurns = vi.fn()

    render(
      <SSEChatInput
        isStreaming={false}
        sendMessage={mockSendMessage}
        clearTurns={mockClearTurns}
      />,
    )

    let addButton = screen.getByRole('button', { name: 'Add current SMILES' })
    await user.click(addButton)

    // After adding, button should be disabled - get fresh reference
    addButton = screen.getByRole('button', { name: 'Add current SMILES' })
    expect(addButton).toBeDisabled()
  })

  it('sends message with chat SMILES separate from workspace SMILES', async () => {
    const user = userEvent.setup()
    useWorkspaceStore.setState({
      currentSmiles: 'CCO',
    })

    const mockSendMessage = vi.fn()
    const mockClearTurns = vi.fn()

    render(
      <SSEChatInput
        isStreaming={false}
        sendMessage={mockSendMessage}
        clearTurns={mockClearTurns}
      />,
    )

    const addButton = screen.getByRole('button', { name: 'Add current SMILES' })
    await user.click(addButton)

    const textareas = screen.getAllByRole('textbox')
    const textarea = textareas[0]
    await user.type(textarea, 'Tell me about this molecule')

    const sendButton = screen.getByRole('button', { name: 'Send' })
    await user.click(sendButton)

    expect(mockSendMessage).toHaveBeenCalledWith('Tell me about this molecule', {
      activeSmiles: 'CCO',
    })
  })

  it('does not auto-add workspace SMILES on message send', async () => {
    const user = userEvent.setup()
    useWorkspaceStore.setState({
      currentSmiles: 'CCO',
      activeFunctionId: 'validate',
    })

    const mockSendMessage = vi.fn()
    const mockClearTurns = vi.fn()

    render(
      <SSEChatInput
        isStreaming={false}
        sendMessage={mockSendMessage}
        clearTurns={mockClearTurns}
      />,
    )

    const textareas = screen.getAllByRole('textbox')
    const textarea = textareas[0]
    await user.type(textarea, 'Tell me about this molecule')

    const sendButton = screen.getByRole('button', { name: 'Send' })
    await user.click(sendButton)

    // activeSmiles should be null since we didn't manually add it
    expect(mockSendMessage).toHaveBeenCalledWith('Tell me about this molecule', {
      activeSmiles: null,
    })
  })
})


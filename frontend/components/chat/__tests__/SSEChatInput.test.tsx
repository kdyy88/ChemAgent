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

  it('adds SMILES tag when "添加当前 SMILES" menu item is clicked', async () => {
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

    // Open dropdown menu
    const dropdownButton = screen.getByRole('button', { name: 'Add data source' })
    await user.click(dropdownButton)

    // Click the menu item
    const menuItem = screen.getByText('添加当前 SMILES')
    await user.click(menuItem)

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

    // Add the tag via dropdown
    const dropdownButton = screen.getByRole('button', { name: 'Add data source' })
    await user.click(dropdownButton)
    const menuItem = screen.getByText('添加当前 SMILES')
    await user.click(menuItem)

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

    const dropdownButton = screen.getByRole('button', { name: 'Add data source' })
    await user.click(dropdownButton)
    const menuItem = screen.getByText('添加当前 SMILES')
    await user.click(menuItem)

    // The full SMILES should be in title attribute
    expect(screen.getByTitle(longSmiles)).toBeInTheDocument()
    // But displayed text should be truncated with ellipsis
    const element = screen.getByText(/🧪/)
    expect(element.textContent).toMatch(/🧪.*…/)
  })

  it('disables dropdown button when SMILES is already added', async () => {
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

    let dropdownButton = screen.getByRole('button', { name: 'Add data source' })
    await user.click(dropdownButton)
    const menuItem = screen.getByText('添加当前 SMILES')
    await user.click(menuItem)

    // After adding, the dropdown button should be disabled
    dropdownButton = screen.getByRole('button', { name: 'Add data source' })
    expect(dropdownButton).toBeDisabled()
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

    const dropdownButton = screen.getByRole('button', { name: 'Add data source' })
    await user.click(dropdownButton)
    const menuItem = screen.getByText('添加当前 SMILES')
    await user.click(menuItem)

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

  it('shows disabled menu items for upload file and specify website', async () => {
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

    const dropdownButton = screen.getByRole('button', { name: 'Add data source' })
    await user.click(dropdownButton)

    // Check that unavailable options exist with "暂未开放" label
    expect(screen.getByText('上传文件')).toBeInTheDocument()
    expect(screen.getByText('指定网站')).toBeInTheDocument()
    const disabledItems = screen.getAllByText('暂未开放')
    expect(disabledItems.length).toBe(2)
  })
})


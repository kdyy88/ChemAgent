import { describe, it, expect } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { ConnectionStatusBadge } from '../ConnectionStatusBadge'

describe('ConnectionStatusBadge', () => {
  it('renders "已连接" for connected status', () => {
    render(React.createElement(ConnectionStatusBadge, { status: 'connected' }))
    expect(screen.getByText('已连接')).toBeDefined()
  })

  it('renders "连接中…" for connecting status', () => {
    render(React.createElement(ConnectionStatusBadge, { status: 'connecting' }))
    expect(screen.getByText('连接中…')).toBeDefined()
  })

  it('renders "重连中…" for reconnecting status', () => {
    render(React.createElement(ConnectionStatusBadge, { status: 'reconnecting' }))
    expect(screen.getByText('重连中…')).toBeDefined()
  })

  it('renders "已断开" for disconnected status', () => {
    render(React.createElement(ConnectionStatusBadge, { status: 'disconnected' }))
    expect(screen.getByText('已断开')).toBeDefined()
  })
})

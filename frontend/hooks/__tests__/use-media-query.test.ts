import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useMediaQuery } from '../use-media-query'

type ChangeListener = (event: { matches: boolean }) => void

function mockMatchMedia(matches: boolean) {
  const listeners: ChangeListener[] = []

  const mql = {
    matches,
    addEventListener: vi.fn((_event: string, listener: ChangeListener) => {
      listeners.push(listener)
    }),
    removeEventListener: vi.fn((_event: string, listener: ChangeListener) => {
      const idx = listeners.indexOf(listener)
      if (idx >= 0) listeners.splice(idx, 1)
    }),
    // helper to simulate a media query change event
    _trigger(newMatches: boolean) {
      listeners.forEach((l) => l({ matches: newMatches }))
    },
  }

  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockReturnValue(mql),
  })

  return mql
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useMediaQuery()', () => {
  it('returns false initially when matchMedia reports no match', () => {
    mockMatchMedia(false)
    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'))
    expect(result.current).toBe(false)
  })

  it('returns true initially when matchMedia reports a match', () => {
    mockMatchMedia(true)
    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'))
    expect(result.current).toBe(true)
  })

  it('updates to true when a change event fires with matches=true', () => {
    const mql = mockMatchMedia(false)
    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'))

    act(() => mql._trigger(true))

    expect(result.current).toBe(true)
  })

  it('updates to false when a change event fires with matches=false', () => {
    const mql = mockMatchMedia(true)
    const { result } = renderHook(() => useMediaQuery('(prefers-color-scheme: dark)'))

    act(() => mql._trigger(false))

    expect(result.current).toBe(false)
  })

  it('registers an event listener on mount', () => {
    const mql = mockMatchMedia(false)
    renderHook(() => useMediaQuery('(min-width: 768px)'))

    expect(mql.addEventListener).toHaveBeenCalledWith('change', expect.any(Function))
  })

  it('removes the event listener on unmount', () => {
    const mql = mockMatchMedia(false)
    const { unmount } = renderHook(() => useMediaQuery('(min-width: 768px)'))

    unmount()

    expect(mql.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
  })

  it('passes the query string to matchMedia', () => {
    const mql = mockMatchMedia(false)
    renderHook(() => useMediaQuery('(max-width: 1024px)'))

    expect(window.matchMedia).toHaveBeenCalledWith('(max-width: 1024px)')
  })
})

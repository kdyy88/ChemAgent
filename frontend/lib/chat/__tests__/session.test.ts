import { describe, it, expect, beforeEach } from 'vitest'
import { loadStoredSessionId, persistSessionId } from '../session'

const KEY = 'chemagent.session_id'

beforeEach(() => {
  localStorage.clear()
})

describe('loadStoredSessionId()', () => {
  it('returns null when localStorage is empty', () => {
    expect(loadStoredSessionId()).toBeNull()
  })

  it('returns the stored string when present', () => {
    localStorage.setItem(KEY, 'sess-abc-123')
    expect(loadStoredSessionId()).toBe('sess-abc-123')
  })

  it('returns null after the key has been removed', () => {
    localStorage.setItem(KEY, 'some-id')
    localStorage.removeItem(KEY)
    expect(loadStoredSessionId()).toBeNull()
  })
})

describe('persistSessionId()', () => {
  it('writes the session id to localStorage', () => {
    persistSessionId('new-session-id')
    expect(localStorage.getItem(KEY)).toBe('new-session-id')
  })

  it('overwrites an existing value', () => {
    localStorage.setItem(KEY, 'old')
    persistSessionId('new')
    expect(localStorage.getItem(KEY)).toBe('new')
  })

  it('removes the key when called with null', () => {
    localStorage.setItem(KEY, 'existing')
    persistSessionId(null)
    expect(localStorage.getItem(KEY)).toBeNull()
  })

  it('is a no-op when called with null and key does not exist', () => {
    expect(() => persistSessionId(null)).not.toThrow()
    expect(localStorage.getItem(KEY)).toBeNull()
  })
})

const SESSION_STORAGE_KEY = 'chemagent.session_id'

export function loadStoredSessionId(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(SESSION_STORAGE_KEY)
}

export function persistSessionId(sessionId: string | null): void {
  if (typeof window === 'undefined') return

  if (sessionId) {
    window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId)
    return
  }

  window.localStorage.removeItem(SESSION_STORAGE_KEY)
}

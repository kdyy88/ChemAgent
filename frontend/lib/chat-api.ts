import type { ChatModelCatalogResponse } from '@/lib/sse-types'

function resolveApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim()
  if (configured) return configured.replace(/\/$/, '')
  if (typeof window !== 'undefined') return window.location.origin
  return 'http://127.0.0.1:8000'
}

const BASE_URL = resolveApiBaseUrl()

export async function fetchAvailableModels(): Promise<ChatModelCatalogResponse> {
  const res = await fetch(`${BASE_URL}/api/chat/models`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return await res.json() as ChatModelCatalogResponse
}
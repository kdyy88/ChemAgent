import type { ChatModelCatalogResponse } from '@/lib/sse-types'

function resolveApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim()
  if (configured) return configured.replace(/\/$/, '')
  if (typeof window !== 'undefined') return ''
  return 'http://127.0.0.1:8000'
}

export async function fetchAvailableModels(): Promise<ChatModelCatalogResponse> {
  const baseUrl = resolveApiBaseUrl()
  const res = await fetch(`${baseUrl}/api/v1/chat/models`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return await res.json() as ChatModelCatalogResponse
}
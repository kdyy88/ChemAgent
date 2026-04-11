/**
 * artifact-api — fetch engine artifacts from the data-plane REST endpoint.
 *
 * Artifacts are produced when ChemSessionEngine._intercept_and_collapse_artifact
 * strips large content (SDF, PDBQT) from tool_end events and stores them in
 * Redis with a 1-hour TTL.
 *
 * GET /api/v1/chat/artifacts/{artifact_id}
 * → { artifact_id: string, data: unknown }
 */

function resolveApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim()
  if (configured) return configured.replace(/\/$/, '')
  if (typeof window !== 'undefined') return window.location.origin
  return 'http://127.0.0.1:8000'
}

const BASE_URL = resolveApiBaseUrl()

export async function fetchArtifact(artifactId: string): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/api/v1/chat/artifacts/${encodeURIComponent(artifactId)}`)
  if (res.status === 404) throw new Error(`Artifact ${artifactId} not found or expired`)
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  const json = await res.json() as { artifact_id: string; data: unknown }
  return json.data
}

export interface PlanDocument {
  plan_id: string
  plan_file_ref: string
  status: string
  summary: string
  revision: number
  content: string
}

export async function fetchPlanDocument(sessionId: string, planId: string): Promise<PlanDocument> {
  const url = new URL(`${BASE_URL}/api/v1/chat/plans/${encodeURIComponent(planId)}`)
  url.searchParams.set('session_id', sessionId)
  const res = await fetch(url.toString())
  if (res.status === 404) throw new Error(`Plan ${planId} not found or expired`)
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return await res.json() as PlanDocument
}

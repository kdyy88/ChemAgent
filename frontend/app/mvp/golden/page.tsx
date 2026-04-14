'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useMemo, useState } from 'react'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import {
  ArrowRight,
  Atom,
  Binary,
  Bot,
  GitBranchPlus,
  Radar,
  RefreshCcw,
  Sparkles,
  TestTubeDiagonal,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

type MoleculeNode = {
  node_id: string
  handle: string
  canonical_smiles: string
  display_name: string
  parent_node_id?: string | null
  origin?: string
  status: string
  diagnostics: Record<string, unknown>
  artifact_ids: string[]
  hover_text?: string
}

type AsyncJob = {
  job_id: string
  job_type: string
  target_handle: string
  status: string
  artifact_id?: string | null
  result_summary?: string
  stale_reason?: string
  approval_state?: string
  job_args?: Record<string, unknown>
}

type WorkspaceProjection = {
  project_id: string
  workspace_id: string
  version: number
  scenario_kind?: string | null
  root_handle?: string | null
  candidate_handles: string[]
  active_view_id?: string | null
  viewport: {
    focused_handles: string[]
    reference_handle?: string | null
  }
  nodes: Record<string, MoleculeNode>
  handle_bindings: Record<string, { handle: string; node_id: string }>
  async_jobs: Record<string, AsyncJob>
  rules: Array<{ rule_id: string; kind: string; text: string; normalized_value?: string }>
}

type WorkspaceSnapshotResponse = {
  session_id: string
  workspace: WorkspaceProjection
  version: number
  pending_job_count: number
}

type WorkspaceEventsResponse = {
  session_id: string
  version: number
  events: Array<Record<string, unknown>>
  pending_job_count: number
}

type EventRecord = {
  id: string
  type: string
  payload: Record<string, unknown>
}

const GOLDEN_PROMPT = '以伊布替尼为母本，保留丙烯酰胺 warhead，要求并环吲哚新骨架，生成3个候选，在单一视口比较母本和3个子分子，并为3个子分子生成3D构象。'

const LOCALE_PREFIX_PATTERN = /^\/(zh|en)(?=\/|$)/

function resolveApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim()
  if (configured) return configured.replace(/\/$/, '')
  if (typeof window !== 'undefined') return window.location.origin
  return 'http://127.0.0.1:8000'
}

function createId() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2)
}

function getNodeByHandle(workspace: WorkspaceProjection | null, handle: string | null | undefined) {
  if (!workspace || !handle) return null
  const binding = workspace.handle_bindings[handle]
  if (!binding) return null
  return workspace.nodes[binding.node_id] ?? null
}

function prettyJson(payload: unknown) {
  return JSON.stringify(payload, null, 2)
}

const API_BASE = resolveApiBaseUrl()

export default function GoldenMvpDemoPage() {
  const pathname = usePathname()
  const [sessionId, setSessionId] = useState(() => `golden-${createId()}`)
  const [turnId, setTurnId] = useState(() => createId())
  const [message, setMessage] = useState(GOLDEN_PROMPT)
  const [isStreaming, setIsStreaming] = useState(false)
  const [status, setStatus] = useState('Idle')
  const [assistantText, setAssistantText] = useState('')
  const [lastError, setLastError] = useState('')
  const [events, setEvents] = useState<EventRecord[]>([])
  const [workspaceSnapshot, setWorkspaceSnapshot] = useState<WorkspaceSnapshotResponse | null>(null)
  const [workspaceBuffer, setWorkspaceBuffer] = useState<WorkspaceEventsResponse | null>(null)

  const workspace = workspaceSnapshot?.workspace ?? null
  const localePrefix = useMemo(() => {
    const matched = pathname?.match(LOCALE_PREFIX_PATTERN)
    return matched ? matched[0] : ''
  }, [pathname])
  const rootNode = getNodeByHandle(workspace, workspace?.root_handle)
  const candidateNodes = useMemo(() => {
    if (!workspace) return []
    return workspace.candidate_handles
      .map((handle) => getNodeByHandle(workspace, handle))
      .filter((node): node is MoleculeNode => node !== null)
  }, [workspace])
  const jobs = useMemo(() => {
    return workspace ? Object.values(workspace.async_jobs) : []
  }, [workspace])
  const graphNodes = useMemo(() => {
    if (!workspace) return [] as Array<{
      id: string
      handle: string
      label: string
      type: 'root' | 'candidate'
      x: number
      y: number
      status: string
      diagnosticsCount: number
      jobStatus?: string
    }>

    const nodes: Array<{
      id: string
      handle: string
      label: string
      type: 'root' | 'candidate'
      x: number
      y: number
      status: string
      diagnosticsCount: number
      jobStatus?: string
    }> = []

    if (rootNode) {
      const rootJob = jobs.find((job) => job.target_handle === rootNode.handle)
      nodes.push({
        id: rootNode.node_id,
        handle: rootNode.handle,
        label: rootNode.display_name || 'Ibrutinib',
        type: 'root',
        x: 380,
        y: 88,
        status: rootNode.status,
        diagnosticsCount: Object.keys(rootNode.diagnostics || {}).length,
        jobStatus: rootJob?.status,
      })
    }

    candidateNodes.forEach((node, index) => {
      const xPositions = [120, 380, 640]
      const candidateJob = jobs.find((job) => job.target_handle === node.handle)
      nodes.push({
        id: node.node_id,
        handle: node.handle,
        label: node.display_name || node.handle,
        type: 'candidate',
        x: xPositions[index] ?? 380,
        y: 282,
        status: node.status,
        diagnosticsCount: Object.keys(node.diagnostics || {}).length,
        jobStatus: candidateJob?.status,
      })
    })

    return nodes
  }, [candidateNodes, jobs, rootNode, workspace])

  const workspaceEvents = useMemo(() => {
    const streamSide = events.filter((event) => {
      return (
        event.type.startsWith('workspace.') ||
        event.type.startsWith('job.') ||
        event.type === 'molecule.upserted' ||
        event.type === 'relation.upserted' ||
        event.type === 'viewport.changed' ||
        event.type === 'rules.updated' ||
        event.type === 'artifact.ready'
      )
    })
    const buffered = (workspaceBuffer?.events ?? []).map((payload) => ({
      id: createId(),
      type: String(payload.type ?? 'unknown'),
      payload,
    }))
    return [...streamSide, ...buffered].slice(0, 20)
  }, [events, workspaceBuffer])

  const appendEvent = (payload: Record<string, unknown>) => {
    setEvents((current) => [{ id: createId(), type: String(payload.type ?? 'unknown'), payload }, ...current].slice(0, 80))
  }

  const refreshWorkspaceSnapshot = async () => {
    const response = await fetch(`${API_BASE}/api/v1/chat/workspace/${sessionId}`, { cache: 'no-store' })
    if (!response.ok) throw new Error(`workspace snapshot HTTP ${response.status}`)
    const data = await response.json() as WorkspaceSnapshotResponse
    setWorkspaceSnapshot(data)
  }

  const refreshWorkspaceEvents = async () => {
    const response = await fetch(`${API_BASE}/api/v1/chat/workspace/${sessionId}/events`, { cache: 'no-store' })
    if (!response.ok) throw new Error(`workspace events HTTP ${response.status}`)
    const data = await response.json() as WorkspaceEventsResponse
    setWorkspaceBuffer(data)
  }

  const refreshWorkspace = async () => {
    try {
      await Promise.all([refreshWorkspaceSnapshot(), refreshWorkspaceEvents()])
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
    }
  }

  const runStream = async (url: string, body: Record<string, unknown>, nextStatus: string) => {
    setIsStreaming(true)
    setStatus(nextStatus)
    setLastError('')

    try {
      await fetchEventSource(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        openWhenHidden: true,
        onmessage: (msg) => {
          if (!msg.data) return
          try {
            const payload = JSON.parse(msg.data) as Record<string, unknown>
            appendEvent(payload)
            const type = String(payload.type ?? '')
            if (type === 'token') {
              setAssistantText((current) => current + String(payload.content ?? ''))
            }
            if (type === 'assistant.message') {
              setAssistantText(String(payload.content ?? ''))
            }
            if (type === 'error') {
              setStatus('Error')
              setLastError(String(payload.error ?? 'Unknown error'))
              setIsStreaming(false)
            }
            if (type === 'done') {
              setStatus('Completed')
              setIsStreaming(false)
              void refreshWorkspace()
            }
          } catch {
            // ignore malformed frames on the demo page
          }
        },
        onopen: async (response) => {
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`)
          }
        },
        onclose: () => {
          setIsStreaming(false)
          void refreshWorkspace()
        },
        onerror: (error) => {
          setStatus('Error')
          setLastError(error instanceof Error ? error.message : String(error))
          setIsStreaming(false)
          throw error
        },
      })
    } catch (error) {
      if ((error as Error)?.name !== 'AbortError') {
        setLastError(error instanceof Error ? error.message : String(error))
      }
      setIsStreaming(false)
    }
  }

  const handleLaunch = async () => {
    const nextTurnId = createId()
    setTurnId(nextTurnId)
    setEvents([])
    setAssistantText('')
    setWorkspaceSnapshot(null)
    setWorkspaceBuffer(null)
    await runStream(
      `${API_BASE}/api/v1/chat/stream`,
      {
        session_id: sessionId,
        turn_id: nextTurnId,
        message,
      },
      'Launching golden-path MVP run',
    )
  }

  const handlePollPending = async () => {
    const nextTurnId = createId()
    setTurnId(nextTurnId)
    await runStream(
      `${API_BASE}/api/v1/chat/pending/poll`,
      {
        session_id: sessionId,
        turn_id: nextTurnId,
      },
      'Polling pending conformer jobs',
    )
  }

  return (
    <main className="min-h-screen bg-[linear-gradient(180deg,#f3fafb_0%,#f4f7fb_32%,#eef4ff_100%)] text-slate-950">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-8 md:px-8">
        <div className="flex flex-col gap-4 rounded-[28px] border border-sky-100/80 bg-white/80 p-6 shadow-[0_20px_60px_rgba(20,65,120,0.08)] backdrop-blur md:flex-row md:items-end md:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-sky-900">
              <Sparkles className="h-3.5 w-3.5" />
              Golden Scenario Demo
            </div>
            <div>
              <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-950 md:text-4xl">
                ChemAgent Scaffold-Hop Workbench
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                这个页面直接体验当前 MVP 主路径：自然语言触发伊布替尼母本建模、固定 3 个候选分支、单视口对比、3D 长任务提交，以及 workspace delta 与 artifact 指针回流。
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Link href={`${localePrefix}/mvp`} className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 transition hover:border-sky-300 hover:text-slate-950">
              <TestTubeDiagonal className="h-4 w-4" />
              MVP Smoke
            </Link>
            <Link href={localePrefix || '/'} className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 transition hover:border-sky-300 hover:text-slate-950">
              <ArrowRight className="h-4 w-4" />
              Main App
            </Link>
          </div>
        </div>

        <div className="grid gap-6 xl:grid-cols-[420px_minmax(0,1fr)]">
          <Card className="border-sky-100 bg-white/90 shadow-[0_14px_40px_rgba(51,94,159,0.10)]">
            <CardHeader>
              <CardTitle>Run Control</CardTitle>
              <CardDescription>直接命中后端黄金场景专用路径。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Session ID</label>
                <Input value={sessionId} onChange={(event) => setSessionId(event.target.value)} />
              </div>
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Turn ID</label>
                <Input value={turnId} onChange={(event) => setTurnId(event.target.value)} />
              </div>
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Prompt</label>
                <Textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={8} className="resize-y" />
              </div>
              <div className="flex flex-wrap gap-3">
                <Button onClick={handleLaunch} disabled={isStreaming || !message.trim()} className="gap-2">
                  <Bot className="h-4 w-4" />
                  Launch Demo
                </Button>
                <Button variant="secondary" onClick={handlePollPending} disabled={isStreaming} className="gap-2">
                  <RefreshCcw className="h-4 w-4" />
                  Poll Jobs
                </Button>
                <Button variant="outline" onClick={() => void refreshWorkspace()} disabled={isStreaming} className="gap-2">
                  <Binary className="h-4 w-4" />
                  Refresh Snapshot
                </Button>
              </div>

              <div className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <Radar className="h-4 w-4 text-sky-700" />
                  Run Status
                </div>
                <div className="mt-3 space-y-3 text-sm text-slate-700">
                  <div className="rounded-xl border border-slate-200 bg-white p-3">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Status</div>
                    <div className="mt-1 text-base font-medium text-slate-950">{status}</div>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white p-3">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Assistant Summary</div>
                    <div className="mt-2 min-h-24 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                      {assistantText || '等待黄金场景节点或 SSE token 输出。'}
                    </div>
                  </div>
                  <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-rose-800">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-rose-500">Latest Error</div>
                    <div className="mt-2 min-h-12 whitespace-pre-wrap text-sm">{lastError || 'No error'}</div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-6">
            <Card className="overflow-hidden border-emerald-100 bg-white/90 shadow-[0_14px_40px_rgba(18,104,86,0.10)]">
              <CardHeader>
                <CardTitle>Single Viewport</CardTitle>
                <CardDescription>
                  当前 projection 里的母本与 3 个候选会在这里聚合显示。{workspace ? ` Workspace v${workspace.version}` : ''}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
                  <div className="rounded-[24px] border border-sky-100 bg-[linear-gradient(135deg,rgba(14,165,233,0.08),rgba(255,255,255,0.7))] p-4">
                    <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
                      <Atom className="h-4 w-4 text-sky-700" />
                      Root Molecule
                    </div>
                    {rootNode ? (
                      <MoleculeCard node={rootNode} accent="root" />
                    ) : (
                      <EmptyCard text="还没有 root molecule。先点击 Launch Demo。" />
                    )}
                  </div>

                  <div className="rounded-[24px] border border-amber-100 bg-[linear-gradient(135deg,rgba(250,204,21,0.10),rgba(255,255,255,0.7))] p-4">
                    <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
                      <GitBranchPlus className="h-4 w-4 text-amber-700" />
                      Candidate Branches
                    </div>
                    <div className="grid gap-3">
                      {candidateNodes.length === 0 ? (
                        <EmptyCard text="还没有 candidates。" />
                      ) : (
                        candidateNodes.map((node) => <MoleculeCard key={node.node_id} node={node} accent="candidate" compact />)
                      )}
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                  <Card className="border-slate-200 bg-slate-50/70 lg:col-span-2">
                    <CardHeader>
                      <CardTitle className="text-sm">Knowledge Graph View</CardTitle>
                      <CardDescription>用单一树视图展示母本、3 个候选以及候选 3D job 状态。</CardDescription>
                    </CardHeader>
                    <CardContent>
                      {graphNodes.length === 0 ? (
                        <EmptyCard text="还没有节点。启动 demo 后会显示 root -> candidate_1..3 的树。" />
                      ) : (
                        <WorkspaceTreeGraph nodes={graphNodes} />
                      )}
                    </CardContent>
                  </Card>

                  <Card className="border-slate-200 bg-slate-50/70">
                    <CardHeader>
                      <CardTitle className="text-sm">Rule Set</CardTitle>
                      <CardDescription>后端当前持有的结构化约束。</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {workspace?.rules.length ? workspace.rules.map((rule) => (
                          <div key={rule.rule_id} className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
                            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">{rule.kind}</div>
                            <div className="mt-1 text-slate-900">{rule.text}</div>
                            {rule.normalized_value ? <div className="mt-1 text-xs text-slate-500">{rule.normalized_value}</div> : null}
                          </div>
                        )) : <EmptyCard text="尚未加载规则。" />}
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="border-slate-200 bg-slate-50/70">
                    <CardHeader>
                      <CardTitle className="text-sm">Conformer Jobs</CardTitle>
                      <CardDescription>3 个候选的 3D 长任务状态。</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {jobs.length ? jobs.map((job) => (
                          <div key={job.job_id} className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
                            <div className="flex items-center justify-between gap-3">
                              <div className="font-medium text-slate-950">{job.target_handle}</div>
                              <span className={cn(
                                'rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]',
                                job.status === 'completed' && 'bg-emerald-100 text-emerald-800',
                                job.status === 'running' && 'bg-sky-100 text-sky-800',
                                job.status === 'stale' && 'bg-amber-100 text-amber-800',
                                job.status !== 'completed' && job.status !== 'running' && job.status !== 'stale' && 'bg-slate-100 text-slate-700',
                              )}>{job.status}</span>
                            </div>
                            <div className="mt-1 text-xs text-slate-500">{job.job_id}</div>
                            <div className="mt-2 text-xs text-slate-600">args: {prettyJson(job.job_args ?? {})}</div>
                            {job.artifact_id ? <div className="mt-2 text-xs text-sky-700">artifact: {job.artifact_id}</div> : null}
                            {job.result_summary ? <div className="mt-2 text-sm text-slate-700">{job.result_summary}</div> : null}
                            {job.stale_reason ? <div className="mt-2 text-sm text-amber-700">{job.stale_reason}</div> : null}
                          </div>
                        )) : <EmptyCard text="尚未创建 3D jobs。" />}
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </CardContent>
            </Card>

            <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
              <Card className="border-violet-100 bg-white/90 shadow-[0_14px_40px_rgba(90,84,187,0.10)]">
                <CardHeader>
                  <CardTitle>Workspace Event Feed</CardTitle>
                  <CardDescription>SSE 流和缓存事件合并后的最近事件。</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="max-h-[520px] space-y-3 overflow-auto pr-1">
                    {workspaceEvents.length === 0 ? (
                      <EmptyCard text="还没有事件。启动 demo 后会出现 workspace.delta、job.started、artifact.ready 等。" />
                    ) : workspaceEvents.map((event) => (
                      <div key={event.id} className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-violet-700">{event.type}</div>
                        <pre className="mt-2 overflow-auto text-xs leading-6 text-slate-700">{prettyJson(event.payload)}</pre>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <Card className="border-slate-200 bg-white/90 shadow-[0_14px_40px_rgba(77,90,110,0.10)]">
                <CardHeader>
                  <CardTitle>Snapshot Summary</CardTitle>
                  <CardDescription>前端重连时直接读取的 workspace 快照。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <SummaryStat label="Scenario" value={workspace?.scenario_kind || 'n/a'} />
                  <SummaryStat label="Workspace ID" value={workspace?.workspace_id || 'n/a'} />
                  <SummaryStat label="Projection Version" value={workspace ? String(workspace.version) : '0'} />
                  <SummaryStat label="Focused Handles" value={workspace?.viewport.focused_handles.join(', ') || 'n/a'} />
                  <SummaryStat label="Pending Jobs" value={String(workspaceSnapshot?.pending_job_count ?? workspaceBuffer?.pending_job_count ?? 0)} />
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}

function MoleculeCard({ node, accent, compact = false }: { node: MoleculeNode; accent: 'root' | 'candidate'; compact?: boolean }) {
  return (
    <div className={cn(
      'rounded-[22px] border p-4',
      accent === 'root' ? 'border-sky-200 bg-white shadow-[0_10px_24px_rgba(56,130,246,0.10)]' : 'border-amber-200 bg-white shadow-[0_10px_24px_rgba(245,158,11,0.10)]',
    )}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">{node.handle}</div>
          <div className="mt-1 text-base font-semibold text-slate-950">{node.display_name || node.handle}</div>
        </div>
        <span className={cn(
          'rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]',
          accent === 'root' ? 'bg-sky-100 text-sky-800' : 'bg-amber-100 text-amber-800',
        )}>{node.status}</span>
      </div>
      <div className="mt-3 rounded-xl bg-slate-50 p-3 font-mono text-xs leading-6 break-all text-slate-700">{node.canonical_smiles}</div>
      {!compact ? (
        <div className="mt-3 grid gap-2 text-xs text-slate-600">
          <div>origin: {node.origin || 'root_commit'}</div>
          <div>artifacts: {node.artifact_ids.length}</div>
          <div>diagnostics: {Object.keys(node.diagnostics || {}).length}</div>
        </div>
      ) : null}
    </div>
  )
}

function EmptyCard({ text }: { text: string }) {
  return <div className="rounded-[20px] border border-dashed border-slate-300 bg-white/70 p-4 text-sm text-slate-500">{text}</div>
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-1 break-all text-sm font-medium text-slate-950">{value}</div>
    </div>
  )
}

function WorkspaceTreeGraph({
  nodes,
}: {
  nodes: Array<{
    id: string
    handle: string
    label: string
    type: 'root' | 'candidate'
    x: number
    y: number
    status: string
    diagnosticsCount: number
    jobStatus?: string
  }>
}) {
  const root = nodes.find((node) => node.type === 'root')
  const candidates = nodes.filter((node) => node.type === 'candidate')

  return (
    <div className="overflow-hidden rounded-[28px] border border-slate-200 bg-[radial-gradient(circle_at_top,_rgba(14,165,233,0.12),_transparent_42%),linear-gradient(180deg,_rgba(255,255,255,0.98),_rgba(241,245,249,0.98))] p-4">
      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-slate-600">
        <span className="rounded-full bg-sky-100 px-2.5 py-1 font-semibold text-sky-800">Root</span>
        <span className="rounded-full bg-amber-100 px-2.5 py-1 font-semibold text-amber-800">Candidates</span>
        <span className="rounded-full bg-emerald-100 px-2.5 py-1 font-semibold text-emerald-800">3D Jobs</span>
      </div>

      <div className="relative h-[430px] overflow-auto rounded-[24px] border border-white/70 bg-white/75 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
        <svg viewBox="0 0 760 420" className="absolute inset-0 h-full w-full">
          <defs>
            <linearGradient id="graph-link" x1="0%" x2="100%" y1="0%" y2="100%">
              <stop offset="0%" stopColor="#0ea5e9" stopOpacity="0.65" />
              <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.7" />
            </linearGradient>
          </defs>
          {root && candidates.map((candidate) => (
            <path
              key={`${root.id}-${candidate.id}`}
              d={`M ${root.x} ${root.y + 58} C ${root.x} ${root.y + 126}, ${candidate.x} ${candidate.y - 76}, ${candidate.x} ${candidate.y - 14}`}
              fill="none"
              stroke="url(#graph-link)"
              strokeWidth="3"
              strokeDasharray={candidate.jobStatus === 'completed' ? '0' : '6 7'}
              strokeLinecap="round"
            />
          ))}
        </svg>

        <div className="relative h-full w-full min-w-[760px]">
          {nodes.map((node) => (
            <div
              key={node.id}
              className={cn(
                'absolute w-[220px] -translate-x-1/2 rounded-[24px] border p-4 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur',
                node.type === 'root'
                  ? 'border-sky-200 bg-[linear-gradient(180deg,rgba(240,249,255,0.98),rgba(255,255,255,0.98))]'
                  : 'border-amber-200 bg-[linear-gradient(180deg,rgba(255,251,235,0.98),rgba(255,255,255,0.98))]'
              )}
              style={{ left: `${node.x}px`, top: `${node.y}px` }}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">{node.handle}</div>
                  <div className="mt-1 text-sm font-semibold text-slate-950">{node.label}</div>
                </div>
                <span className={cn(
                  'rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]',
                  node.type === 'root' ? 'bg-sky-100 text-sky-800' : 'bg-amber-100 text-amber-800'
                )}>
                  {node.status}
                </span>
              </div>

              <div className="mt-3 grid gap-2 text-xs text-slate-600">
                <div className="rounded-xl bg-slate-50 px-3 py-2">
                  diagnostics: <span className="font-semibold text-slate-900">{node.diagnosticsCount}</span>
                </div>
                <div className="rounded-xl bg-slate-50 px-3 py-2">
                  3D job: <span className="font-semibold text-slate-900">{node.jobStatus || 'not started'}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
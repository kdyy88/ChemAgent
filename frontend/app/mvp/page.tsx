'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { FlaskConical, Radar, RefreshCw, Send, TestTubeDiagonal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

type EventRecord = {
  id: string
  type: string
  payload: Record<string, unknown>
}

function resolveApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim()
  if (configured) return configured.replace(/\/$/, '')
  if (typeof window !== 'undefined') return window.location.origin
  return 'http://127.0.0.1:8000'
}

const API_BASE = resolveApiBaseUrl()
const STREAM_URL = `${API_BASE}/api/v1/chat/stream`
const POLL_URL = `${API_BASE}/api/v1/chat/pending/poll`
const FORCE_CONFORMER_URL = `${API_BASE}/api/v1/chat/mvp/conformer`
const LOCALE_PREFIX_PATTERN = /^\/(zh|en)(?=\/|$)/

function createId() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2)
}

const PRESET_PROMPTS = [
  {
    label: '3D Conformer',
    message: '请为乙醇生成 3D conformer。SMILES 是 CCO。并把结果写入当前 workspace。',
    activeSmiles: 'CCO',
  },
  {
    label: 'Prepare PDBQT',
    message: '请为咖啡因准备 PDBQT 文件。SMILES 是 CN1C=NC2=C1C(=O)N(C)C(=O)N2C。',
    activeSmiles: 'CN1C=NC2=C1C(=O)N(C)C(=O)N2C',
  },
]

export default function MvpSmokePage() {
  const pathname = usePathname()
  const [sessionId, setSessionId] = useState(() => createId())
  const [activeSmiles, setActiveSmiles] = useState('CCO')
  const [message, setMessage] = useState(PRESET_PROMPTS[0].message)
  const [events, setEvents] = useState<EventRecord[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [status, setStatus] = useState('Idle')
  const [lastError, setLastError] = useState('')

  const workspaceEvents = useMemo(
    () => events.filter((event) => event.type.startsWith('workspace.') || event.type.startsWith('job.') || event.type === 'viewport.changed' || event.type === 'rules.updated'),
    [events],
  )

  const toolEvents = useMemo(
    () => [...events].reverse().filter((event) => event.type === 'tool_start' || event.type === 'tool_end'),
    [events],
  )

  const heavyToolSummary = useMemo(() => {
    const heavyTools = toolEvents
      .map((event) => String(event.payload.tool ?? ''))
      .filter((tool) => tool === 'tool_build_3d_conformer' || tool === 'tool_prepare_pdbqt')
    return Array.from(new Set(heavyTools))
  }, [toolEvents])

  const assistantText = useMemo(() => {
    return [...events]
      .reverse()
      .filter((event) => event.type === 'token')
      .map((event) => String(event.payload.content ?? ''))
      .join('')
  }, [events])

  const localePrefix = useMemo(() => {
    const matched = pathname?.match(LOCALE_PREFIX_PATTERN)
    return matched ? matched[0] : ''
  }, [pathname])

  const appendEvent = (payload: Record<string, unknown>) => {
    setEvents((current) => [
      {
        id: createId(),
        type: String(payload.type ?? 'unknown'),
        payload,
      },
      ...current,
    ])
  }

  const runSseRequest = async (url: string, body: Record<string, unknown>, nextStatus: string) => {
    setIsStreaming(true)
    setLastError('')
    setStatus(nextStatus)

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
            const eventType = String(payload.type ?? '')
            if (eventType === 'done') {
              setStatus('Completed')
              setIsStreaming(false)
            } else if (eventType === 'error') {
              setStatus('Error')
              setLastError(String(payload.error ?? 'Unknown error'))
              setIsStreaming(false)
            }
          } catch {
            // Ignore malformed SSE frames in the smoke page.
          }
        },
        onopen: async (response) => {
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`)
          }
        },
        onclose: () => {
          setIsStreaming(false)
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

  const handleSend = async () => {
    setEvents([])
    await runSseRequest(
      STREAM_URL,
      {
        message,
        session_id: sessionId,
        turn_id: createId(),
        active_smiles: activeSmiles || null,
      },
      'Streaming chat run',
    )
  }

  const handlePollPending = async () => {
    await runSseRequest(
      POLL_URL,
      {
        session_id: sessionId,
        turn_id: createId(),
      },
      'Polling pending jobs',
    )
  }

  const handleForceConformer = async () => {
    setEvents([])
    await runSseRequest(
      FORCE_CONFORMER_URL,
      {
        session_id: sessionId,
        turn_id: createId(),
        smiles: activeSmiles || 'CCO',
        name: 'mvp_smoke',
      },
      'Running deterministic 3D conformer smoke test',
    )
  }

  const handlePreset = (preset: (typeof PRESET_PROMPTS)[number]) => {
    setMessage(preset.message)
    setActiveSmiles(preset.activeSmiles)
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(12,74,110,0.08),_transparent_35%),linear-gradient(180deg,_#f8fafc_0%,_#eef2ff_100%)] text-slate-950">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-8 md:px-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-white/80 px-3 py-1 text-xs font-medium text-sky-900 shadow-sm backdrop-blur">
              <TestTubeDiagonal className="h-3.5 w-3.5" />
              MVP Smoke Test
            </div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">ChemAgent MVP Playground</h1>
            <p className="max-w-3xl text-sm text-slate-600">
              这个页面只验证 MVP 主链路是否跑通：聊天 SSE、workspace/job 事件、以及 pending job 轮询回流。
            </p>
          </div>
          <Link href={localePrefix || '/'} className="text-sm text-slate-600 underline underline-offset-4 hover:text-slate-950">
            Back to main app
          </Link>
          <Link href={`${localePrefix}/mvp/golden`} className="text-sm text-sky-700 underline underline-offset-4 hover:text-sky-900">
            Open golden-path demo
          </Link>
        </div>

        <div className="grid gap-6 lg:grid-cols-[420px_minmax(0,1fr)]">
          <Card className="border-sky-100 bg-white/90 p-5 shadow-lg shadow-sky-100/50">
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Session ID</label>
                <Input value={sessionId} onChange={(event) => setSessionId(event.target.value)} />
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Active SMILES</label>
                <Input value={activeSmiles} onChange={(event) => setActiveSmiles(event.target.value)} placeholder="CCO" />
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Prompt</label>
                <Textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={7} className="resize-y" />
              </div>

              <div className="flex flex-wrap gap-2">
                {PRESET_PROMPTS.map((preset) => (
                  <Button key={preset.label} type="button" variant="outline" size="sm" onClick={() => handlePreset(preset)}>
                    {preset.label}
                  </Button>
                ))}
              </div>

              <div className="flex flex-wrap gap-3">
                <Button onClick={handleSend} disabled={isStreaming || !message.trim()} className="gap-2">
                  <Send className="h-4 w-4" />
                  Send Run
                </Button>
                <Button variant="outline" onClick={handleForceConformer} disabled={isStreaming || !activeSmiles.trim()} className="gap-2">
                  <TestTubeDiagonal className="h-4 w-4" />
                  Force 3D Tool Test
                </Button>
                <Button variant="secondary" onClick={handlePollPending} disabled={isStreaming} className="gap-2">
                  <RefreshCw className="h-4 w-4" />
                  Poll Pending Jobs
                </Button>
                <Button variant="ghost" onClick={() => setEvents([])} disabled={isStreaming}>
                  Clear Log
                </Button>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                <div className="flex items-center gap-2 font-medium text-slate-900">
                  <FlaskConical className="h-4 w-4 text-sky-700" />
                  Smoke-test steps
                </div>
                <ol className="mt-2 space-y-1.5 pl-5 text-sm list-decimal">
                  <li>先点 Send Run，观察是否出现 `job.started` / `job.progress`。</li>
                  <li>如果 LLM 没实际调用重工具，改点 Force 3D Tool Test，直接验证后端 job 链路。</li>
                  <li>如果长任务进入 pending，点 Poll Pending Jobs。</li>
                  <li>看到 `job.completed`、`workspace.delta`、`artifact` 就说明 MVP 主链路打通。</li>
                </ol>
              </div>
            </div>
          </Card>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <Card className="border-emerald-100 bg-white/90 p-5 shadow-lg shadow-emerald-100/40">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Run State</p>
                  <h2 className="mt-1 text-lg font-semibold text-slate-950">Execution Summary</h2>
                </div>
                <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-800">
                  <Radar className="h-3.5 w-3.5" />
                  {status}
                </div>
              </div>

              <div className="mt-4 space-y-4 text-sm text-slate-700">
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Assistant text</div>
                  <div className="min-h-24 rounded-xl border border-slate-200 bg-slate-50 p-3 whitespace-pre-wrap">
                    {assistantText || 'No streamed assistant text yet.'}
                  </div>
                </div>

                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Latest error</div>
                  <div className="min-h-16 rounded-xl border border-rose-200 bg-rose-50 p-3 text-rose-800 whitespace-pre-wrap">
                    {lastError || 'No error'}
                  </div>
                </div>

                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Heavy tool calls</div>
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                    {heavyToolSummary.length === 0
                      ? 'This run did not actually invoke tool_build_3d_conformer or tool_prepare_pdbqt.'
                      : heavyToolSummary.join(', ')}
                  </div>
                </div>

                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Workspace / Job events</div>
                  <div className="max-h-[420px] space-y-2 overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-3">
                    {workspaceEvents.length === 0 ? (
                      <p className="text-slate-500">No workspace events yet.</p>
                    ) : (
                      workspaceEvents.map((event) => (
                        <div key={event.id} className="rounded-lg border border-slate-200 bg-white p-3">
                          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">{event.type}</div>
                          <pre className="mt-2 overflow-auto text-xs text-slate-700">{JSON.stringify(event.payload, null, 2)}</pre>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Tool lifecycle</div>
                  <div className="max-h-48 space-y-2 overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-3">
                    {toolEvents.length === 0 ? (
                      <p className="text-slate-500">No tool lifecycle events yet.</p>
                    ) : (
                      toolEvents.map((event) => (
                        <div key={event.id} className="rounded-lg border border-slate-200 bg-white p-3">
                          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-700">{event.type}</div>
                          <pre className="mt-2 overflow-auto text-xs text-slate-700">{JSON.stringify(event.payload, null, 2)}</pre>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </Card>

            <Card className="border-slate-200 bg-white/90 p-5 shadow-lg shadow-slate-200/60">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Raw SSE</p>
                <h2 className="mt-1 text-lg font-semibold text-slate-950">Event Log</h2>
              </div>
              <div className="mt-4 max-h-[760px] space-y-2 overflow-auto rounded-2xl border border-slate-200 bg-slate-950 p-3 text-slate-100">
                {events.length === 0 ? (
                  <p className="text-sm text-slate-400">No SSE events yet.</p>
                ) : (
                  events.map((event) => (
                    <div key={event.id} className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300">{event.type}</div>
                      <pre className="mt-2 overflow-auto text-xs text-slate-200">{JSON.stringify(event.payload, null, 2)}</pre>
                    </div>
                  ))
                )}
              </div>
            </Card>
          </div>
        </div>
      </div>
    </main>
  )
}
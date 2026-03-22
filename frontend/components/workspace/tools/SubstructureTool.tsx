'use client'

import { useState } from 'react'
import { CheckCircle2, XCircle, AlertTriangle, Shield, ShieldAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { substructureMatch, type SubstructureResponse } from '@/lib/chem-api'
import { ToolLayout, InfoRow, ResultCard } from './ToolLayout'
import { FieldLabel } from '../shared'

const SMARTS_EXAMPLES = [
  { label: '苯环', smarts: 'c1ccccc1' },
  { label: '羧基 -COOH', smarts: '[CX3](=O)[OX2H1]' },
  { label: '胺基 -NH2', smarts: '[NX3;H2]' },
  { label: '酰胺', smarts: '[NX3][CX3](=[OX1])' },
  { label: '磺酰胺', smarts: '[#16X4](=[OX1])(=[OX1])([#7])' },
]

export function SubstructureTool() {
  const { currentSmiles } = useWorkspaceStore()
  const [smarts, setSmarts] = useState('')
  const [result, setResult] = useState<SubstructureResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function execute() {
    if (!currentSmiles.trim() || !smarts.trim()) return
    setLoading(true); setError(null); setResult(null)
    try {
      setResult(await substructureMatch(currentSmiles.trim(), smarts.trim()))
    } catch (err: any) {
      setError(err.message || '搜索失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolLayout
      title="子结构搜索 + PAINS 筛查"
      description="使用 SMARTS 模式匹配目标分子中的官能团，同时自动运行 PAINS（泛筛选干扰化合物）筛查。"
      buttonLabel="执行搜索"
      loadingLabel="正在搜索..."
      onExecute={execute}
      loading={loading}
      error={error}
      disabled={!smarts.trim()}
      resultSlot={result && <SubstructureResultCard data={result} />}
    >
      <div>
        <FieldLabel required>SMARTS 模式</FieldLabel>
        <Input
          value={smarts}
          onChange={(e) => { setSmarts(e.target.value); setResult(null) }}
          className="font-mono text-sm"
          placeholder="c1ccccc1"
        />
        <div className="flex flex-wrap gap-1.5 mt-2">
          {SMARTS_EXAMPLES.map(ex => (
            <button
              key={ex.label}
              onClick={() => { setSmarts(ex.smarts); setResult(null) }}
              className="rounded-full border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
            >
              {ex.label}
            </button>
          ))}
        </div>
      </div>
    </ToolLayout>
  )
}

function SubstructureResultCard({ data }: { data: SubstructureResponse }) {
  if (!data.is_valid) {
    return (
      <ResultCard>
        <div className="flex items-center gap-2">
          <XCircle className="h-4 w-4 text-red-500" />
          <span className="text-sm font-semibold text-red-700">搜索失败</span>
        </div>
        <p className="text-xs text-red-600">{data.error}</p>
      </ResultCard>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Substructure match result */}
      <ResultCard>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {data.matched ? (
              <CheckCircle2 className="h-4 w-4 text-green-500" />
            ) : (
              <XCircle className="h-4 w-4 text-muted-foreground" />
            )}
            <span className="text-sm font-semibold">
              {data.matched ? `匹配成功 (${data.match_count} 处)` : '未找到匹配'}
            </span>
          </div>
          <Badge variant="outline" className="text-[10px] font-mono">{data.smarts_pattern}</Badge>
        </div>

        {data.highlighted_image && (
          <div className="flex justify-center">
            <img
              src={`data:image/png;base64,${data.highlighted_image}`}
              alt="子结构匹配"
              className="max-w-[320px] rounded-md border"
            />
          </div>
        )}

        {data.matched && (
          <div className="text-[10px] text-muted-foreground bg-muted/40 rounded-md px-3 py-2">
            匹配原子索引：{data.match_atoms.map((m, i) => `[${m.join(',')}]`).join(' ')}
          </div>
        )}
      </ResultCard>

      {/* PAINS screening */}
      <ResultCard>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {data.pains_clean ? (
              <Shield className="h-4 w-4 text-green-500" />
            ) : (
              <ShieldAlert className="h-4 w-4 text-red-500" />
            )}
            <span className="text-sm font-semibold">PAINS 筛查</span>
          </div>
          {data.pains_clean ? (
            <Badge className="text-[10px] bg-green-100 text-green-700 border-green-200">
              通过 — 无 PAINS 警示
            </Badge>
          ) : (
            <Badge className="text-[10px] bg-red-100 text-red-700 border-red-200">
              <AlertTriangle className="h-2.5 w-2.5 mr-0.5" />
              发现 {data.pains_alerts.length} 个 PAINS 警示
            </Badge>
          )}
        </div>

        {data.pains_alerts.length > 0 && (
          <div className="flex flex-col gap-1">
            {data.pains_alerts.map((alert, i) => (
              <div key={i} className="flex items-center gap-1.5 text-xs text-red-600 bg-red-50 rounded-md px-3 py-1.5 border border-red-200">
                <AlertTriangle className="h-3 w-3 shrink-0" />
                {alert.name}
              </div>
            ))}
          </div>
        )}
      </ResultCard>
    </div>
  )
}

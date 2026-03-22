'use client'

import { useState } from 'react'
import { CheckCircle2, XCircle, Layers } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { murckoScaffold, type ScaffoldResponse } from '@/lib/chem-api'
import { ToolLayout, InfoRow, ResultCard } from './ToolLayout'

export function ScaffoldTool() {
  const { currentSmiles } = useWorkspaceStore()
  const [result, setResult] = useState<ScaffoldResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function execute() {
    if (!currentSmiles.trim()) return
    setLoading(true); setError(null); setResult(null)
    try {
      setResult(await murckoScaffold(currentSmiles.trim()))
    } catch (err: any) {
      setError(err.message || '提取失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolLayout
      title="Murcko 骨架提取"
      description="提取分子的 Bemis-Murcko 核心骨架（保留环系和连接臂）以及碳骨架（将所有原子极简化为碳），用于骨架跃迁分析和化合物聚类。"
      buttonLabel="提取骨架"
      loadingLabel="正在提取..."
      onExecute={execute}
      loading={loading}
      error={error}
      resultSlot={result && <ScaffoldResultCard data={result} />}
    />
  )
}

function ScaffoldResultCard({ data }: { data: ScaffoldResponse }) {
  if (!data.is_valid) {
    return (
      <ResultCard>
        <div className="flex items-center gap-2">
          <XCircle className="h-4 w-4 text-red-500" />
          <span className="text-sm font-semibold text-red-700">提取失败</span>
        </div>
        <p className="text-xs text-red-600">{data.error}</p>
      </ResultCard>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Side by side: Original → Scaffold */}
      <ResultCard>
        <div className="flex items-center gap-1.5 mb-2">
          <Layers className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">骨架分解</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Original */}
          <div className="flex flex-col items-center gap-2">
            <Badge variant="outline" className="text-[10px]">原始分子</Badge>
            {data.molecule_image && (
              <img
                src={`data:image/png;base64,${data.molecule_image}`}
                alt="原始分子"
                className="max-w-[200px] rounded-md border"
              />
            )}
            <p className="text-[10px] font-mono text-muted-foreground break-all text-center">{data.smiles}</p>
          </div>

          {/* Scaffold */}
          <div className="flex flex-col items-center gap-2">
            <Badge className="text-[10px] bg-primary/10 text-primary border-primary/20">Murcko 骨架</Badge>
            {data.scaffold_image && (
              <img
                src={`data:image/png;base64,${data.scaffold_image}`}
                alt="Murcko 骨架"
                className="max-w-[200px] rounded-md border"
              />
            )}
            <p className="text-[10px] font-mono text-muted-foreground break-all text-center">{data.scaffold_smiles}</p>
          </div>
        </div>
      </ResultCard>

      {/* Generic scaffold */}
      {data.generic_scaffold_smiles && (
        <ResultCard>
          <div className="rounded-md border border-border/40 px-3 py-1">
            <InfoRow label="Murcko 骨架 SMILES" value={
              <span className="font-mono text-[10px] break-all select-all">{data.scaffold_smiles}</span>
            } />
            <InfoRow label="碳骨架 SMILES" value={
              <span className="font-mono text-[10px] break-all select-all">{data.generic_scaffold_smiles}</span>
            } />
          </div>
        </ResultCard>
      )}
    </div>
  )
}

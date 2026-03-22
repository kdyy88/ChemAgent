'use client'

import { useState } from 'react'
import { CheckCircle2, XCircle, Atom } from 'lucide-react'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { computeMolProperties, type MolPropertiesResponse } from '@/lib/chem-api'
import { ToolLayout, InfoRow, ResultCard } from './ToolLayout'

export function MolPropertyTool() {
  const { currentSmiles } = useWorkspaceStore()
  const [result, setResult] = useState<MolPropertiesResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function execute() {
    if (!currentSmiles.trim()) return
    setLoading(true); setError(null); setResult(null)
    try {
      setResult(await computeMolProperties(currentSmiles.trim()))
    } catch (err: any) {
      setError(err.message || '计算失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolLayout
      title="核心物理属性"
      description="使用 Open Babel 引擎计算精确质量、形式电荷、自旋多重度等核心物理属性。与 RDKit 描述符互补。"
      buttonLabel="计算属性"
      loadingLabel="正在计算..."
      onExecute={execute}
      loading={loading}
      error={error}
      resultSlot={result && <MolPropertyResultCard data={result} />}
    />
  )
}

function MolPropertyResultCard({ data }: { data: MolPropertiesResponse }) {
  if (!data.is_valid) {
    return (
      <ResultCard>
        <div className="flex items-center gap-2">
          <XCircle className="h-4 w-4 text-red-500" />
          <span className="text-sm font-semibold text-red-700">计算失败</span>
        </div>
        <p className="text-xs text-red-600">{data.error}</p>
      </ResultCard>
    )
  }

  return (
    <ResultCard>
      <div className="flex items-center gap-1.5">
        <Atom className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">物理属性 (OpenBabel)</span>
      </div>

      <div className="rounded-md border border-border/40 px-3 py-1">
        <InfoRow label="分子式" value={<span className="font-medium">{data.formula}</span>} />
        <InfoRow label="精确质量 (Exact Mass)" value={`${data.exact_mass} Da`} />
        <InfoRow label="分子量 (MW)" value={`${data.molecular_weight} Da`} />
        <InfoRow label="形式电荷" value={
          <span className={data.formal_charge !== 0 ? 'text-amber-600 font-semibold' : ''}>
            {data.formal_charge > 0 ? `+${data.formal_charge}` : data.formal_charge}
          </span>
        } />
        <InfoRow label="自旋多重度" value={data.spin_multiplicity} />
        <InfoRow label="重原子数" value={data.heavy_atom_count} />
        <InfoRow label="总原子数" value={data.atom_count} />
        <InfoRow label="化学键数" value={data.bond_count} />
        <InfoRow label="可旋转键" value={data.rotatable_bonds} />
      </div>
    </ResultCard>
  )
}

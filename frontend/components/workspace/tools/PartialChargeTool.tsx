'use client'

import { useState } from 'react'
import { XCircle, Zap } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { computePartialCharges, type PartialChargeResponse, type ChargeAtom } from '@/lib/chem-api'
import { ToolLayout, InfoRow, ResultCard } from './ToolLayout'
import { FieldLabel } from '../shared'

const CHARGE_METHODS = [
  { value: 'gasteiger', label: 'Gasteiger (默认)' },
  { value: 'mmff94', label: 'MMFF94' },
  { value: 'qeq', label: 'QEq' },
  { value: 'eem', label: 'EEM' },
]

export function PartialChargeTool() {
  const { currentSmiles } = useWorkspaceStore()
  const [method, setMethod] = useState('gasteiger')
  const [result, setResult] = useState<PartialChargeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)

  async function execute() {
    if (!currentSmiles.trim()) return
    setLoading(true); setError(null); setResult(null); setShowAll(false)
    try {
      setResult(await computePartialCharges(currentSmiles.trim(), method))
    } catch (err: any) {
      setError(err.message || '计算失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolLayout
      title="原子偏电荷分析"
      description="计算分子中每个原子的偏电荷 (Partial Charge)，可视化静电分布。支持 Gasteiger、MMFF94、QEq、EEM 四种电荷模型。"
      buttonLabel="计算偏电荷"
      loadingLabel="正在计算..."
      onExecute={execute}
      loading={loading}
      error={error}
      resultSlot={result && <ChargeResultCard data={result} showAll={showAll} onToggle={() => setShowAll(!showAll)} />}
    >
      <div>
        <FieldLabel required>电荷模型</FieldLabel>
        <select
          value={method}
          onChange={(e) => { setMethod(e.target.value); setResult(null) }}
          className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {CHARGE_METHODS.map(m => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>
      </div>
    </ToolLayout>
  )
}

function ChargeResultCard({
  data,
  showAll,
  onToggle,
}: {
  data: PartialChargeResponse
  showAll: boolean
  onToggle: () => void
}) {
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

  const displayAtoms = showAll ? data.atoms : data.heavy_atoms

  return (
    <div className="flex flex-col gap-3">
      {/* Summary */}
      <ResultCard>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Zap className="h-4 w-4 text-amber-500" />
            <span className="text-sm font-semibold">偏电荷分析</span>
          </div>
          <Badge className="text-[10px] bg-primary/10 text-primary border-primary/20">
            {data.charge_model.toUpperCase()}
          </Badge>
        </div>
        <div className="rounded-md border border-border/40 px-3 py-1">
          <InfoRow label="SMILES" value={<span className="font-mono text-[10px] break-all">{data.smiles}</span>} />
          <InfoRow label="总电荷" value={
            <span className={data.total_charge > 0.01 ? 'text-red-500' : data.total_charge < -0.01 ? 'text-blue-500' : ''}>
              {data.total_charge > 0 ? '+' : ''}{data.total_charge.toFixed(4)}
            </span>
          } />
          <InfoRow label="总原子数" value={data.atom_count} />
          <InfoRow label="重原子数" value={data.heavy_atom_count} />
        </div>
      </ResultCard>

      {/* Charge table */}
      <ResultCard>
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">原子电荷表</p>
          <button
            onClick={onToggle}
            className="text-[10px] text-primary hover:underline"
          >
            {showAll ? '仅显示重原子' : `显示全部 (含 H, 共${data.atom_count})`}
          </button>
        </div>

        <div className="max-h-[400px] overflow-y-auto rounded-md border border-border/40">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur-sm">
              <tr>
                <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">#</th>
                <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">元素</th>
                <th className="text-right px-3 py-1.5 font-medium text-muted-foreground">偏电荷</th>
                <th className="text-left px-3 py-1.5 font-medium text-muted-foreground w-24">分布</th>
              </tr>
            </thead>
            <tbody>
              {displayAtoms.map((atom: ChargeAtom) => (
                <ChargeRow key={atom.idx} atom={atom} />
              ))}
            </tbody>
          </table>
        </div>
      </ResultCard>
    </div>
  )
}

function ChargeRow({ atom }: { atom: ChargeAtom }) {
  const isPositive = atom.charge > 0.005
  const isNegative = atom.charge < -0.005

  // Bar width: normalize charge to [-0.5, 0.5] range for visual
  const barPct = Math.min(Math.abs(atom.charge) / 0.5, 1) * 50

  return (
    <tr className="border-b border-border/30 last:border-0 hover:bg-muted/30 transition-colors">
      <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{atom.idx}</td>
      <td className="px-3 py-1.5 font-medium">{atom.element}</td>
      <td className={`px-3 py-1.5 text-right tabular-nums font-mono ${
        isPositive ? 'text-red-500' : isNegative ? 'text-blue-500' : 'text-muted-foreground'
      }`}>
        {atom.charge > 0 ? '+' : ''}{atom.charge.toFixed(4)}
      </td>
      <td className="px-3 py-1.5">
        <div className="flex items-center h-3">
          <div className="relative w-full h-2 bg-muted/50 rounded-full">
            {isPositive && (
              <div
                className="absolute left-1/2 h-full bg-red-400 rounded-r-full"
                style={{ width: `${barPct}%` }}
              />
            )}
            {isNegative && (
              <div
                className="absolute right-1/2 h-full bg-blue-400 rounded-l-full"
                style={{ width: `${barPct}%` }}
              />
            )}
            <div className="absolute left-1/2 top-0 w-px h-full bg-border" />
          </div>
        </div>
      </td>
    </tr>
  )
}

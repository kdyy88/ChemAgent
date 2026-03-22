'use client'

import { useState } from 'react'
import { CheckCircle2, XCircle, AlertTriangle, FlaskConical } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { computeDescriptors, type DescriptorsResponse, type DescriptorsResult } from '@/lib/chem-api'
import { ToolLayout, InfoRow, ResultCard } from './ToolLayout'
import { FieldLabel } from '../shared'

export function DescriptorsTool() {
  const { currentSmiles, currentName, setName } = useWorkspaceStore()
  const [result, setResult] = useState<DescriptorsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function execute() {
    if (!currentSmiles.trim()) return
    setLoading(true); setError(null); setResult(null)
    try {
      setResult(await computeDescriptors(currentSmiles.trim(), currentName.trim()))
    } catch (err: any) {
      setError(err.message || '计算失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <ToolLayout
      title="综合分子描述符"
      buttonLabel="计算描述符"
      loadingLabel="正在计算..."
      onExecute={execute}
      loading={loading}
      error={error}
      resultSlot={result && <DescriptorResultCard data={result} />}
    >
      <div>
        <FieldLabel>化合物名称</FieldLabel>
        <Input value={currentName} onChange={(e) => setName(e.target.value)} placeholder="Aspirin" className="text-sm" />
      </div>
    </ToolLayout>
  )
}

function DescriptorResultCard({ data }: { data: DescriptorsResponse }) {
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

  const d = data.descriptors
  const lip = data.lipinski

  return (
    <div className="flex flex-col gap-3">
      {/* Lipinski badge */}
      <ResultCard>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <FlaskConical className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold">
              {data.name || data.smiles}
            </span>
          </div>
          {lip.pass ? (
            <Badge className="text-[10px] bg-green-100 text-green-700 border-green-200">
              <CheckCircle2 className="h-2.5 w-2.5 mr-0.5" />
              Lipinski 通过 (0 违规)
            </Badge>
          ) : (
            <Badge className="text-[10px] bg-red-100 text-red-700 border-red-200">
              <AlertTriangle className="h-2.5 w-2.5 mr-0.5" />
              {lip.violations} 条违规
            </Badge>
          )}
        </div>

        <p className="text-xs text-muted-foreground font-mono">{data.formula}</p>

        {data.structure_image && (
          <div className="flex justify-center">
            <img
              src={`data:image/png;base64,${data.structure_image}`}
              alt="2D 结构"
              className="max-w-[280px] rounded-md border"
            />
          </div>
        )}
      </ResultCard>

      {/* Lipinski 4 criteria */}
      <ResultCard>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Lipinski 五规则</p>
        <div className="rounded-md border border-border/40 px-3 py-1">
          {Object.entries(lip.criteria).map(([key, c]) => {
            const labels: Record<string, string> = {
              molecular_weight: `分子量 (≤${c.threshold})`,
              log_p: `LogP (≤${c.threshold})`,
              h_bond_donors: `氢键供体 (≤${c.threshold})`,
              h_bond_acceptors: `氢键受体 (≤${c.threshold})`,
            }
            return (
              <InfoRow
                key={key}
                label={labels[key] || key}
                value={
                  <span className={c.pass ? 'text-green-600' : 'text-red-500 font-semibold'}>
                    {c.value} {c.pass ? '✓' : '✗'}
                  </span>
                }
              />
            )
          })}
        </div>
      </ResultCard>

      {/* Extended descriptors */}
      <ResultCard>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">扩展描述符</p>
        <div className="rounded-md border border-border/40 px-3 py-1">
          <InfoRow label="TPSA (极性表面积)" value={`${d.tpsa} Å²`} />
          <InfoRow label="可旋转键" value={d.rotatable_bonds} />
          <InfoRow label="环数" value={d.ring_count} />
          <InfoRow label="芳环数" value={d.aromatic_rings} />
          <InfoRow label="Fsp3 (碳饱和度)" value={d.fraction_csp3} />
          <InfoRow label="重原子数" value={d.heavy_atom_count} />
        </div>
      </ResultCard>

      {/* Drug-likeness scores */}
      <ResultCard>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">药物评估指标</p>
        <div className="rounded-md border border-border/40 px-3 py-1">
          <InfoRow
            label="QED (药物相似性)"
            value={
              <span className={d.qed >= 0.5 ? 'text-green-600' : 'text-amber-500'}>
                {d.qed.toFixed(3)} {d.qed >= 0.67 ? '优秀' : d.qed >= 0.5 ? '良好' : '偏低'}
              </span>
            }
          />
          <InfoRow
            label="SA Score (合成可及性)"
            value={
              <span className={d.sa_score <= 4 ? 'text-green-600' : d.sa_score <= 6 ? 'text-amber-500' : 'text-red-500'}>
                {d.sa_score.toFixed(2)} {d.sa_score <= 3 ? '易合成' : d.sa_score <= 6 ? '中等' : '难合成'}
              </span>
            }
          />
        </div>
      </ResultCard>
    </div>
  )
}

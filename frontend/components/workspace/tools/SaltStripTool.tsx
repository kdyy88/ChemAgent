'use client'

import { useState } from 'react'
import { CheckCircle2, XCircle, Sparkles, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { saltStrip, type SaltStripResponse } from '@/lib/chem-api'
import { ToolLayout, InfoRow, ResultCard } from './ToolLayout'

const SALT_EXAMPLES = [
  { label: '盐酸苯丙胺', smiles: 'CC(N)c1ccccc1.Cl' },
  { label: '柠檬酸钠', smiles: '[Na+].[Na+].[Na+].OC(CC([O-])=O)(CC([O-])=O)C([O-])=O' },
  { label: '纯净 Aspirin', smiles: 'CC(=O)Oc1ccccc1C(=O)O' },
]

export function SaltStripTool() {
  const { currentSmiles, setSmiles } = useWorkspaceStore()
  const [result, setResult] = useState<SaltStripResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function execute() {
    if (!currentSmiles.trim()) return
    setLoading(true); setError(null); setResult(null)
    try {
      setResult(await saltStrip(currentSmiles.trim()))
    } catch (err: any) {
      setError(err.message || '处理失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Custom example chips for salt-specific molecules */}
      <div className="flex flex-wrap gap-1.5">
        {SALT_EXAMPLES.map(ex => (
          <button
            key={ex.label}
            onClick={() => { setSmiles(ex.smiles); setResult(null); setError(null) }}
            className="rounded-full border px-2.5 py-0.5 text-[11px] text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
          >
            {ex.label}
          </button>
        ))}
      </div>

      <ToolLayout
        title="脱盐与中和"
        description="自动剥离盐离子 (HCl, Na⁺ 等) 并中和异常电荷，提取最大母核分子。这是数据清洗的第一步。"
        buttonLabel="执行脱盐与中和"
        loadingLabel="处理中..."
        smilesPlaceholder="CC(N)c1ccccc1.Cl (含盐酸根)"
        onExecute={execute}
        loading={loading}
        error={error}
        resultSlot={result && <SaltStripResultCard data={result} />}
      />
    </div>
  )
}

function SaltStripResultCard({ data }: { data: SaltStripResponse }) {
  if (!data.is_valid) {
    return (
      <ResultCard>
        <div className="flex items-center gap-2">
          <XCircle className="h-4 w-4 text-red-500" />
          <span className="text-sm font-semibold text-red-700">处理失败</span>
        </div>
        <p className="text-xs text-red-600">{data.error}</p>
      </ResultCard>
    )
  }

  const changed = data.had_salts || data.charge_neutralized

  return (
    <ResultCard>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          {changed ? (
            <Sparkles className="h-4 w-4 text-amber-500" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-green-500" />
          )}
          <span className="text-sm font-semibold">
            {changed ? '分子已清洗' : '分子已是纯净状态'}
          </span>
        </div>
        <div className="flex gap-1">
          {data.had_salts && (
            <Badge className="text-[10px] bg-amber-100 text-amber-700 border-amber-200">
              <Trash2 className="h-2.5 w-2.5 mr-0.5" />已脱盐
            </Badge>
          )}
          {data.charge_neutralized && (
            <Badge className="text-[10px] bg-blue-100 text-blue-700 border-blue-200">已中和</Badge>
          )}
        </div>
      </div>

      {/* Before → After */}
      <div className="grid grid-cols-1 gap-2">
        <div className="rounded-md bg-muted/50 px-3 py-2">
          <p className="text-[10px] text-muted-foreground mb-1">原始 SMILES</p>
          <p className="text-xs font-mono break-all">{data.original_smiles}</p>
        </div>
        <div className="rounded-md bg-green-50 dark:bg-green-950/30 px-3 py-2 border border-green-200 dark:border-green-800">
          <p className="text-[10px] text-green-600 dark:text-green-400 mb-1">清洗后 SMILES (母核)</p>
          <p className="text-xs font-mono break-all select-all">{data.cleaned_smiles}</p>
        </div>
      </div>

      {data.removed_fragments.length > 0 && (
        <div className="rounded-md border border-red-200 bg-red-50/50 px-3 py-2">
          <p className="text-[10px] text-red-500 mb-1">已移除的盐/离子片段</p>
          <p className="text-xs font-mono">{data.removed_fragments.join(' · ')}</p>
        </div>
      )}

      <div className="rounded-md border border-border/40 px-3 py-1">
        <InfoRow label="母核分子式" value={data.parent_formula} />
        <InfoRow label="母核重原子数" value={data.parent_heavy_atoms} />
      </div>

      {data.structure_image && (
        <div className="flex justify-center">
          <img
            src={`data:image/png;base64,${data.structure_image}`}
            alt="清洗后分子结构"
            className="max-w-[280px] rounded-md border"
          />
        </div>
      )}
    </ResultCard>
  )
}

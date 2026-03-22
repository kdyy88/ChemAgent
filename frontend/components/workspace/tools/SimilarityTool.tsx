'use client'

import { useState } from 'react'
import { XCircle, ArrowLeftRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { computeSimilarity, type SimilarityResponse } from '@/lib/chem-api'
import { InfoRow, ResultCard } from './ToolLayout'
import { FieldLabel, NetworkErrorAlert } from '../shared'

export function SimilarityTool() {
  const [smiles1, setSmiles1] = useState('')
  const [smiles2, setSmiles2] = useState('')
  const [radius, setRadius] = useState(2)
  const [result, setResult] = useState<SimilarityResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function execute() {
    if (!smiles1.trim() || !smiles2.trim()) return
    setLoading(true); setError(null); setResult(null)
    try {
      setResult(await computeSimilarity(smiles1.trim(), smiles2.trim(), radius))
    } catch (err: any) {
      setError(err.message || '计算失败')
    } finally {
      setLoading(false)
    }
  }

  // Quick fill examples
  function fillExample() {
    setSmiles1('CC(=O)Oc1ccccc1C(=O)O')  // Aspirin
    setSmiles2('CC(C)Cc1ccc(cc1)C(C)C(=O)O')  // Ibuprofen
    setResult(null)
  }

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={fillExample}
        className="self-start rounded-full border px-2.5 py-0.5 text-[11px] text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
      >
        示例：Aspirin vs Ibuprofen
      </button>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <FieldLabel required>分子 1 (SMILES)</FieldLabel>
          <Textarea
            value={smiles1}
            onChange={(e) => setSmiles1(e.target.value)}
            className="font-mono text-sm resize-none min-h-[80px]"
            placeholder="CC(=O)Oc1ccccc1C(=O)O"
          />
        </div>
        <div>
          <FieldLabel required>分子 2 (SMILES)</FieldLabel>
          <Textarea
            value={smiles2}
            onChange={(e) => setSmiles2(e.target.value)}
            className="font-mono text-sm resize-none min-h-[80px]"
            placeholder="CC(C)Cc1ccc(cc1)C(C)C(=O)O"
          />
        </div>
      </div>

      <div className="w-48">
        <FieldLabel>指纹半径 (ECFP{radius * 2})</FieldLabel>
        <Input
          type="number" value={radius} min={1} max={6}
          onChange={(e) => setRadius(Number(e.target.value))} className="text-sm"
        />
      </div>

      <Button onClick={execute} disabled={loading || !smiles1.trim() || !smiles2.trim()} className="w-full">
        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {loading ? '正在计算...' : '计算相似度'}
      </Button>

      {error && <NetworkErrorAlert message={error} />}
      {result && <SimilarityResultCard data={result} />}
    </div>
  )
}

function SimilarityResultCard({ data }: { data: SimilarityResponse }) {
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

  const pct = (data.tanimoto * 100).toFixed(1)
  const color = data.tanimoto >= 0.85 ? 'text-green-600' :
                data.tanimoto >= 0.7  ? 'text-blue-600' :
                data.tanimoto >= 0.4  ? 'text-amber-600' : 'text-red-500'

  return (
    <div className="flex flex-col gap-3">
      {/* Tanimoto score spotlight */}
      <ResultCard>
        <div className="flex flex-col items-center py-3 gap-2">
          <ArrowLeftRight className="h-5 w-5 text-muted-foreground" />
          <div className={`text-4xl font-bold tabular-nums ${color}`}>{pct}%</div>
          <p className="text-xs text-muted-foreground">Tanimoto 系数: {data.tanimoto}</p>
          <Badge className={`text-[10px] ${
            data.tanimoto >= 0.85 ? 'bg-green-100 text-green-700 border-green-200' :
            data.tanimoto >= 0.7  ? 'bg-blue-100 text-blue-700 border-blue-200' :
            data.tanimoto >= 0.4  ? 'bg-amber-100 text-amber-700 border-amber-200' :
                                    'bg-red-100 text-red-700 border-red-200'
          }`}>
            {data.interpretation}
          </Badge>
          <p className="text-[10px] text-muted-foreground">{data.fingerprint_type}, {data.n_bits} bits</p>
        </div>
      </ResultCard>

      {/* Two molecules side by side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <MolCard label="分子 1" info={data.molecule_1} />
        <MolCard label="分子 2" info={data.molecule_2} />
      </div>
    </div>
  )
}

function MolCard({ label, info }: { label: string; info: { smiles: string; formula: string; heavy_atoms: number; image: string } }) {
  return (
    <ResultCard>
      <p className="text-xs font-semibold text-muted-foreground">{label}</p>
      <div className="flex justify-center">
        <img
          src={`data:image/png;base64,${info.image}`}
          alt={label}
          className="max-w-[200px] rounded-md border"
        />
      </div>
      <div className="rounded-md border border-border/40 px-3 py-1">
        <InfoRow label="SMILES" value={<span className="font-mono text-[10px] break-all">{info.smiles}</span>} />
        <InfoRow label="分子式" value={info.formula} />
        <InfoRow label="重原子数" value={info.heavy_atoms} />
      </div>
    </ResultCard>
  )
}

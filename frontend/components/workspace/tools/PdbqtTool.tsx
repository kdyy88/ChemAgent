'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { BabelResultCard } from '@/components/chat/BabelResultCard'
import { preparePdbqt, type PdbqtPrepResponse } from '@/lib/chem-api'
import { ExampleChips, FieldLabel, NetworkErrorAlert } from '../shared'

export function PdbqtTool() {
  const { currentSmiles, setSmiles, currentName, setName } = useWorkspaceStore()
  const [ph, setPh] = useState(7.4)
  const [result, setResult] = useState<PdbqtPrepResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function execute() {
    if (!currentSmiles.trim()) return
    setLoading(true); setError(null); setResult(null)
    try {
      setResult(await preparePdbqt(currentSmiles.trim(), currentName.trim(), ph))
    } catch (err: any) {
      setError(err.message || '处理失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <ExampleChips onSelect={(s, n) => { setSmiles(s); setName(n); setResult(null) }} />
      <div className="text-[11px] text-muted-foreground bg-muted/40 rounded-md px-3 py-2 leading-relaxed">
        自动流水线：加氢 (指定 pH) → 3D 构象 (MMFF94) → Gasteiger 电荷分配 → 输出 PDBQT。
      </div>
      <div>
        <FieldLabel required>SMILES</FieldLabel>
        <Textarea
          value={currentSmiles}
          onChange={(e) => setSmiles(e.target.value)}
          className="font-mono text-sm resize-none min-h-[80px]"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <FieldLabel>化合物名称</FieldLabel>
          <Input value={currentName} onChange={(e) => setName(e.target.value)} className="text-sm" placeholder="Ibuprofen" />
        </div>
        <div>
          <FieldLabel required>质子化 pH</FieldLabel>
          <Input
            type="number" value={ph} min={0} max={14} step={0.1}
            onChange={(e) => setPh(Number(e.target.value))} className="text-sm"
          />
        </div>
      </div>
      <Button onClick={execute} disabled={loading || !currentSmiles.trim()} className="w-full">
        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {loading ? '处理中...' : '生成 PDBQT'}
      </Button>
      {error && <NetworkErrorAlert message={error} />}
      {result && <BabelResultCard data={result} />}
    </div>
  )
}

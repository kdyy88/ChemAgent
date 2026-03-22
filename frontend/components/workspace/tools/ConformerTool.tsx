'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { BabelResultCard } from '@/components/chat/BabelResultCard'
import { build3DConformer, type Conformer3DResponse } from '@/lib/chem-api'
import { ExampleChips, FieldLabel, NetworkErrorAlert } from '../shared'

export function ConformerTool() {
  const { currentSmiles, setSmiles, currentName, setName } = useWorkspaceStore()
  const [forcefield, setForcefield] = useState('mmff94')
  const [steps, setSteps] = useState(500)
  const [result, setResult] = useState<Conformer3DResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function execute() {
    if (!currentSmiles.trim()) return
    setLoading(true); setError(null); setResult(null)
    try {
      setResult(await build3DConformer(currentSmiles.trim(), currentName.trim(), forcefield, steps))
    } catch (err: any) {
      setError(err.message || '生成失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <ExampleChips onSelect={(s, n) => { setSmiles(s); setName(n); setResult(null) }} />
      <div>
        <FieldLabel required>SMILES</FieldLabel>
        <Textarea
          value={currentSmiles}
          onChange={(e) => setSmiles(e.target.value)}
          className="font-mono text-sm resize-none min-h-[80px]"
        />
      </div>
      <div>
        <FieldLabel>化合物名称</FieldLabel>
        <Input value={currentName} onChange={(e) => setName(e.target.value)} className="text-sm" placeholder="Aspirin" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <FieldLabel required>力场 (Forcefield)</FieldLabel>
          <select
            value={forcefield}
            onChange={(e) => setForcefield(e.target.value)}
            className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="mmff94">MMFF94 (推荐)</option>
            <option value="uff">UFF</option>
            <option value="gaff">GAFF</option>
          </select>
        </div>
        <div>
          <FieldLabel required>优化步数</FieldLabel>
          <Input
            type="number" value={steps} min={10} max={5000}
            onChange={(e) => setSteps(Number(e.target.value))} className="text-sm"
          />
        </div>
      </div>
      <Button onClick={execute} disabled={loading || !currentSmiles.trim()} className="w-full">
        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {loading ? '正在生成...' : '生成 3D 构象'}
      </Button>
      {error && <NetworkErrorAlert message={error} />}
      {result && result.is_valid && result.energy_kcal_mol != null && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 px-4 py-3">
          <span className="text-lg">⚡</span>
          <div>
            <p className="text-xs text-muted-foreground">系统能量 ({result.forcefield.toUpperCase()})</p>
            <p className="text-sm font-bold text-amber-700 dark:text-amber-400">{result.energy_kcal_mol.toFixed(2)} kcal/mol</p>
          </div>
        </div>
      )}
      {result && <BabelResultCard data={result} />}
    </div>
  )
}

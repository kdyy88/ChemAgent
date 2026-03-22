'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { LipinskiCard } from '@/components/chat/LipinskiCard'
import { analyzeMolecule, type LipinskiResponse } from '@/lib/chem-api'
import { ExampleChips, FieldLabel, NetworkErrorAlert } from '../shared'

export function LipinskiTool() {
  const { currentSmiles, setSmiles, currentName, setName } = useWorkspaceStore()
  const [result, setResult] = useState<LipinskiResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleAnalyze() {
    if (!currentSmiles.trim()) return
    setLoading(true); setError(null); setResult(null)
    try {
      setResult(await analyzeMolecule(currentSmiles.trim(), currentName.trim()))
    } catch (err: any) {
      setError(err.message || '分析失败，请检查服务状态')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <ExampleChips onSelect={(s, n) => { setSmiles(s); setName(n); setResult(null); setError(null) }} />
      <div>
        <FieldLabel required>SMILES</FieldLabel>
        <Textarea
          value={currentSmiles}
          onChange={(e) => { setSmiles(e.target.value); setResult(null) }}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); handleAnalyze() } }}
          placeholder="CC(=O)Oc1ccccc1C(=O)O"
          className="font-mono text-sm resize-none min-h-[80px]"
        />
        <p className="text-[10px] text-muted-foreground/70 mt-1">Ctrl/⌘ + Enter 快速提交</p>
      </div>
      <div>
        <FieldLabel>化合物名称</FieldLabel>
        <Input value={currentName} onChange={(e) => setName(e.target.value)} placeholder="Aspirin" className="text-sm" />
      </div>
      <Button onClick={handleAnalyze} disabled={loading || !currentSmiles.trim()} className="w-full">
        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {loading ? '正在分析...' : '分析分子'}
      </Button>
      {error && <NetworkErrorAlert message={error} />}
      {result && <LipinskiCard data={result} />}
    </div>
  )
}

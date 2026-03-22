'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { BabelResultCard } from '@/components/chat/BabelResultCard'
import { convertFormat, type FormatConversionResponse } from '@/lib/chem-api'
import { ExampleChips, FieldLabel, NetworkErrorAlert } from '../shared'

const FORMATS = ['smi', 'inchi', 'inchikey', 'sdf', 'mol2', 'pdb', 'xyz', 'mol', 'can']

export function ConvertTool() {
  const { currentSmiles, setSmiles } = useWorkspaceStore()
  const [inFmt, setInFmt] = useState('smi')
  const [outFmt, setOutFmt] = useState('sdf')
  const [result, setResult] = useState<FormatConversionResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function execute() {
    if (!currentSmiles.trim()) return
    setLoading(true); setError(null); setResult(null)
    try {
      setResult(await convertFormat(currentSmiles.trim(), inFmt.trim(), outFmt.trim()))
    } catch (err: any) {
      setError(err.message || '转换异常')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <ExampleChips onSelect={(s) => { setSmiles(s); setInFmt('smi'); setResult(null) }} />
      <div>
        <FieldLabel required>分子字符串</FieldLabel>
        <Textarea
          value={currentSmiles}
          onChange={(e) => setSmiles(e.target.value)}
          className="font-mono text-sm resize-none min-h-[80px]"
          placeholder="CC(=O)Oc1ccccc1C(=O)O"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <FieldLabel required>输入格式</FieldLabel>
          <Input 
            value={inFmt} 
            onChange={(e) => setInFmt(e.target.value)} 
            list="formats" 
            className="text-sm font-mono placeholder:text-muted-foreground" 
            placeholder="e.g. smi"
          />
        </div>
        <div>
          <FieldLabel required>输出格式</FieldLabel>
          <Input 
            value={outFmt} 
            onChange={(e) => setOutFmt(e.target.value)} 
            list="formats" 
            className="text-sm font-mono placeholder:text-muted-foreground" 
            placeholder="e.g. sdf"
          />
        </div>
        <datalist id="formats">
          {FORMATS.map(f => <option key={f} value={f} />)}
        </datalist>
      </div>
      
      <Button onClick={execute} disabled={loading || !currentSmiles.trim() || !inFmt.trim() || !outFmt.trim()} className="w-full">
        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {loading ? '正在转换...' : '执行转换'}
      </Button>
      {error && <NetworkErrorAlert message={error} />}
      {result && <BabelResultCard data={result} />}
    </div>
  )
}

'use client'

import { useState } from 'react'
import { AlertCircle, FlaskConical, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { BabelResultCard } from '@/components/chat/BabelResultCard'
import { LipinskiCard } from '@/components/chat/LipinskiCard'
import {
  analyzeMolecule,
  build3DConformer,
  convertFormat,
  preparePdbqt,
} from '@/lib/chem-api'
import type {
  Conformer3DResponse,
  FormatConversionResponse,
  LipinskiResponse,
  PdbqtPrepResponse,
} from '@/lib/chem-api'

// ── Example SMILES chips ──────────────────────────────────────────────────────

const EXAMPLES = [
  { label: 'Aspirin',    smiles: 'CC(=O)Oc1ccccc1C(=O)O' },
  { label: 'Ibuprofen',  smiles: 'CC(C)Cc1ccc(cc1)C(C)C(=O)O' },
  { label: 'Caffeine',   smiles: 'Cn1cnc2c1c(=O)n(c(=O)n2C)C' },
  { label: 'Paclitaxel', smiles: 'O=C(O[C@@H]1C[C@]2(OC(=O)c3ccccc3)[C@@H](O)C[C@@H](O)[C@]2(C)[C@@H](OC(C)=O)[C@@H]1OC(=O)[C@@H](O)[C@@H](NC(=O)c1ccccc1)c1ccccc1)c1ccccc1' },
]

// ── Tab def ───────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'lipinski',  label: '成药分析' },
  { id: 'convert',   label: '格式转换' },
  { id: 'conformer', label: '3D 构象' },
  { id: 'pdbqt',     label: '对接预处理' },
] as const

type TabId = (typeof TABS)[number]['id']

// ── Shared sub-components ─────────────────────────────────────────────────────

function ExampleChips({
  onSelect,
}: {
  onSelect: (smiles: string, label: string) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {EXAMPLES.map((ex) => (
        <button
          key={ex.label}
          onClick={() => onSelect(ex.smiles, ex.label)}
          className="rounded-full border px-2.5 py-0.5 text-[11px] text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
        >
          {ex.label}
        </button>
      ))}
    </div>
  )
}

function NetworkErrorAlert({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50/60 p-3">
      <AlertCircle className="h-4 w-4 text-red-600 mt-0.5 shrink-0" />
      <div className="text-sm text-red-700">
        <p className="font-medium mb-0.5">请求失败</p>
        <p className="text-xs">{message}</p>
      </div>
    </div>
  )
}

function FieldLabel({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="text-xs font-medium text-muted-foreground">
      {children}
      {required && <span className="text-red-500 ml-0.5">*</span>}
      {!required && <span className="opacity-50 ml-1">(可选)</span>}
    </label>
  )
}

// ── Tab 0: Lipinski Analysis (existing) ──────────────────────────────────────

function LipinskiTab() {
  const [smiles, setSmiles] = useState('')
  const [name, setName] = useState('')
  const [result, setResult] = useState<LipinskiResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [networkError, setNetworkError] = useState<string | null>(null)

  async function handleAnalyze() {
    const trimmed = smiles.trim()
    if (!trimmed) return
    setLoading(true); setResult(null); setNetworkError(null)
    try {
      setResult(await analyzeMolecule(trimmed, name.trim()))
    } catch (err) {
      setNetworkError(err instanceof Error ? err.message : '网络错误，请确认后端服务正在运行。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <ExampleChips onSelect={(s, n) => { setSmiles(s); setName(n); setResult(null); setNetworkError(null) }} />
      <div className="flex flex-col gap-1">
        <FieldLabel required>SMILES</FieldLabel>
        <Textarea
          value={smiles}
          onChange={(e) => { setSmiles(e.target.value); setResult(null); setNetworkError(null) }}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); handleAnalyze() } }}
          placeholder="CC(=O)Oc1ccccc1C(=O)O"
          className="font-mono text-sm resize-none min-h-[72px]"
          autoFocus
        />
        <p className="text-[10px] text-muted-foreground/70">Ctrl/⌘ + Enter 快速提交</p>
      </div>
      <div className="flex flex-col gap-1">
        <FieldLabel>化合物名称</FieldLabel>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Aspirin" className="text-sm" />
      </div>
      <Button onClick={handleAnalyze} disabled={loading || !smiles.trim()} className="w-full">
        {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在分析…</> : '分析分子'}
      </Button>
      {networkError && <NetworkErrorAlert message={networkError} />}
      {result && <LipinskiCard data={result} />}
    </div>
  )
}

// ── Tab 1: Format Conversion ──────────────────────────────────────────────────

const FORMAT_OPTIONS = ['smi', 'inchi', 'inchikey', 'sdf', 'mol2', 'pdb', 'xyz', 'mol', 'can']

function ConvertTab() {
  const [molecule, setMolecule] = useState('')
  const [inputFmt, setInputFmt] = useState('smi')
  const [outputFmt, setOutputFmt] = useState('sdf')
  const [result, setResult] = useState<FormatConversionResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [networkError, setNetworkError] = useState<string | null>(null)

  async function handleConvert() {
    const trimmed = molecule.trim()
    if (!trimmed) return
    setLoading(true); setResult(null); setNetworkError(null)
    try {
      setResult(await convertFormat(trimmed, inputFmt, outputFmt))
    } catch (err) {
      setNetworkError(err instanceof Error ? err.message : '网络错误，请确认后端服务正在运行。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <ExampleChips onSelect={(s) => { setMolecule(s); setInputFmt('smi'); setResult(null); setNetworkError(null) }} />
      <div className="flex flex-col gap-1">
        <FieldLabel required>分子字符串</FieldLabel>
        <Textarea
          value={molecule}
          onChange={(e) => { setMolecule(e.target.value); setResult(null); setNetworkError(null) }}
          placeholder="CC(=O)Oc1ccccc1C(=O)O"
          className="font-mono text-sm resize-none min-h-[72px]"
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1">
          <FieldLabel required>输入格式</FieldLabel>
          <select
            value={inputFmt}
            onChange={(e) => setInputFmt(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            {FORMAT_OPTIONS.map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}
            <option value="__custom__">自定义…</option>
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <FieldLabel required>输出格式</FieldLabel>
          <select
            value={outputFmt}
            onChange={(e) => setOutputFmt(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            {FORMAT_OPTIONS.map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}
            <option value="__custom__">自定义…</option>
          </select>
        </div>
      </div>
      {(inputFmt === '__custom__' || outputFmt === '__custom__') && (
        <div className="grid grid-cols-2 gap-2">
          {inputFmt === '__custom__' && (
            <div className="flex flex-col gap-1">
              <FieldLabel required>自定义输入格式</FieldLabel>
              <Input placeholder="e.g. mol2" className="text-sm font-mono"
                onChange={(e) => setInputFmt(e.target.value || '__custom__')} />
            </div>
          )}
          {outputFmt === '__custom__' && (
            <div className="flex flex-col gap-1">
              <FieldLabel required>自定义输出格式</FieldLabel>
              <Input placeholder="e.g. mol2" className="text-sm font-mono"
                onChange={(e) => setOutputFmt(e.target.value || '__custom__')} />
            </div>
          )}
        </div>
      )}
      <Button onClick={handleConvert} disabled={loading || !molecule.trim()} className="w-full">
        {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在转换…</> : '转换格式'}
      </Button>
      {networkError && <NetworkErrorAlert message={networkError} />}
      {result && <BabelResultCard data={result} />}
    </div>
  )
}

// ── Tab 2: 3D Conformer ───────────────────────────────────────────────────────

function ConformerTab() {
  const [smiles, setSmiles] = useState('')
  const [name, setName] = useState('')
  const [forcefield, setForcefield] = useState('mmff94')
  const [steps, setSteps] = useState(500)
  const [result, setResult] = useState<Conformer3DResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [networkError, setNetworkError] = useState<string | null>(null)

  async function handleBuild() {
    const trimmed = smiles.trim()
    if (!trimmed) return
    setLoading(true); setResult(null); setNetworkError(null)
    try {
      setResult(await build3DConformer(trimmed, name.trim(), forcefield, steps))
    } catch (err) {
      setNetworkError(err instanceof Error ? err.message : '网络错误，请确认后端服务正在运行。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <ExampleChips onSelect={(s, n) => { setSmiles(s); setName(n); setResult(null); setNetworkError(null) }} />
      <div className="flex flex-col gap-1">
        <FieldLabel required>SMILES</FieldLabel>
        <Textarea
          value={smiles}
          onChange={(e) => { setSmiles(e.target.value); setResult(null); setNetworkError(null) }}
          placeholder="CC(=O)Oc1ccccc1C(=O)O"
          className="font-mono text-sm resize-none min-h-[72px]"
        />
      </div>
      <div className="flex flex-col gap-1">
        <FieldLabel>化合物名称</FieldLabel>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Aspirin" className="text-sm" />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1">
          <FieldLabel required>力场</FieldLabel>
          <select
            value={forcefield}
            onChange={(e) => setForcefield(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="mmff94">MMFF94（推荐）</option>
            <option value="uff">UFF</option>
            <option value="gaff">GAFF</option>
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <FieldLabel required>优化步数</FieldLabel>
          <Input
            type="number"
            value={steps}
            min={10}
            max={5000}
            onChange={(e) => setSteps(Number(e.target.value))}
            className="text-sm"
          />
        </div>
      </div>
      <Button onClick={handleBuild} disabled={loading || !smiles.trim()} className="w-full">
        {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在生成 3D 构象…</> : '生成 3D 构象'}
      </Button>
      {networkError && <NetworkErrorAlert message={networkError} />}
      {result && <BabelResultCard data={result} />}
    </div>
  )
}

// ── Tab 3: PDBQT Docking Prep ─────────────────────────────────────────────────

function PdbqtTab() {
  const [smiles, setSmiles] = useState('')
  const [name, setName] = useState('')
  const [ph, setPh] = useState(7.4)
  const [result, setResult] = useState<PdbqtPrepResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [networkError, setNetworkError] = useState<string | null>(null)

  async function handlePrep() {
    const trimmed = smiles.trim()
    if (!trimmed) return
    setLoading(true); setResult(null); setNetworkError(null)
    try {
      setResult(await preparePdbqt(trimmed, name.trim(), ph))
    } catch (err) {
      setNetworkError(err instanceof Error ? err.message : '网络错误，请确认后端服务正在运行。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <ExampleChips onSelect={(s, n) => { setSmiles(s); setName(n); setResult(null); setNetworkError(null) }} />
      <div className="text-[11px] text-muted-foreground bg-muted/40 rounded-md px-3 py-2 leading-relaxed">
        自动完成：加氢（指定 pH）→ 3D 构象生成（MMFF94）→ Gasteiger 电荷分配 → PDBQT 输出。
        兼容 AutoDock Vina / Smina / GNINA。
      </div>
      <div className="flex flex-col gap-1">
        <FieldLabel required>SMILES</FieldLabel>
        <Textarea
          value={smiles}
          onChange={(e) => { setSmiles(e.target.value); setResult(null); setNetworkError(null) }}
          placeholder="CC(C)Cc1ccc(cc1)C(C)C(=O)O"
          className="font-mono text-sm resize-none min-h-[72px]"
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1">
          <FieldLabel>化合物名称</FieldLabel>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ibuprofen" className="text-sm" />
        </div>
        <div className="flex flex-col gap-1">
          <FieldLabel required>质子化 pH</FieldLabel>
          <Input
            type="number"
            value={ph}
            min={0}
            max={14}
            step={0.1}
            onChange={(e) => setPh(Number(e.target.value))}
            className="text-sm"
          />
        </div>
      </div>
      <Button onClick={handlePrep} disabled={loading || !smiles.trim()} className="w-full">
        {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在准备对接文件…</> : '生成 PDBQT'}
      </Button>
      {networkError && <NetworkErrorAlert message={networkError} />}
      {result && <BabelResultCard data={result} />}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function SmilesPanelSheet() {
  const [activeTab, setActiveTab] = useState<TabId>('lipinski')

  return (
    <Sheet>
      {/* Trigger button — sits in the page header */}
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 p-6 text-muted-foreground hover:text-foreground"
        >
          <FlaskConical className="h-4 w-4" />
          <span className="hidden sm:inline text-xs">分子工具箱</span>
        </Button>
      </SheetTrigger>

      <SheetContent
        side="right"
        className="w-full sm:max-w-lg flex flex-col gap-0 overflow-y-auto"
      >
        <SheetHeader className="shrink-0 pb-3">
          <SheetTitle className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-primary" />
            分子工具箱
          </SheetTitle>
        </SheetHeader>

        {/* Tab bar */}
        <div className="flex shrink-0 border-b mb-4">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={[
                'flex-1 py-2 text-[11px] font-medium transition-colors border-b-2 -mb-px',
                activeTab === tab.id
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              ].join(' ')}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab panels */}
        <div className="flex-1 flex flex-col gap-3 min-h-0 pb-4">
          {activeTab === 'lipinski'  && <LipinskiTab />}
          {activeTab === 'convert'   && <ConvertTab />}
          {activeTab === 'conformer' && <ConformerTab />}
          {activeTab === 'pdbqt'     && <PdbqtTab />}
        </div>
      </SheetContent>
    </Sheet>
  )
}

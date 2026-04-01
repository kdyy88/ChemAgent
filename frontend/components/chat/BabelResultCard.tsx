'use client'

import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  XCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import type {
  BabelError,
  Conformer3DResult,
  FormatConversionResult,
  PdbqtPrepResult,
} from '@/lib/chem-api'

// ── Types ─────────────────────────────────────────────────────────────────────

type BabelResult = FormatConversionResult | Conformer3DResult | PdbqtPrepResult

export type BabelResponse = BabelResult | BabelError

// ── Helpers ───────────────────────────────────────────────────────────────────

function preview(text: string, lines = 12): string {
  const rows = text.split('\n')
  if (rows.length <= lines) return text
  return rows.slice(0, lines).join('\n') + `\n… (+${rows.length - lines} 行)`
}

function triggerDownload(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ContentPreview({ content, label }: { content: string; label?: string }) {
  const [expanded, setExpanded] = useState(false)
  const rows = content.split('\n')
  const needsTruncate = rows.length > 12
  const displayed = expanded ? content : preview(content)

  return (
    <div className="flex flex-col gap-1">
      {label && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {label} {needsTruncate && !expanded && `(${rows.length} 行，展开查看全部)`}
        </button>
      )}
      <pre className="text-[11px] font-mono leading-relaxed rounded-md bg-muted/60 p-2.5 overflow-x-auto whitespace-pre">
        {displayed}
      </pre>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-border/40 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xs font-medium">{value}</span>
    </div>
  )
}

// ── Error card ────────────────────────────────────────────────────────────────

function BabelErrorCard({ error }: { error: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50/60 p-3.5">
      <XCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
      <div>
        <p className="text-sm font-medium text-red-700 mb-0.5">转换失败</p>
        <p className="text-xs text-red-600 leading-relaxed">{error}</p>
      </div>
    </div>
  )
}

// ── Tool 1: Format Conversion ─────────────────────────────────────────────────

function FormatConversionCard({ data }: { data: FormatConversionResult }) {
  const [copied, setCopied] = useState(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== null) clearTimeout(timeoutRef.current)
    }
  }, [])

  function handleCopy() {
    navigator.clipboard.writeText(data.output)
    setCopied(true)
    if (timeoutRef.current !== null) clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => setCopied(false), 1800)
  }

  const extension: Record<string, string> = {
    sdf: 'sdf', mol2: 'mol2', pdb: 'pdb', xyz: 'xyz', mol: 'mol',
    inchi: 'txt', inchikey: 'txt', smi: 'smi', can: 'smi',
  }
  const ext = extension[data.output_format] ?? data.output_format
  const mime: Record<string, string> = {
    sdf: 'chemical/x-mdl-sdfile', mol2: 'chemical/x-mol2',
    pdb: 'chemical/x-pdb', xyz: 'chemical/x-xyz',
  }
  const mimeType = mime[data.output_format] ?? 'text/plain'
  const filename = `molecule.${ext}`

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border/60 bg-card p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          <span className="text-sm font-semibold">格式转换成功</span>
        </div>
        <div className="flex items-center gap-1">
          <Badge variant="outline" className="text-[10px] py-0 px-1.5 font-mono uppercase">
            {data.input_format}
          </Badge>
          <span className="text-muted-foreground text-xs">→</span>
          <Badge className="text-[10px] py-0 px-1.5 font-mono uppercase bg-primary/10 text-primary border-primary/20">
            {data.output_format}
          </Badge>
        </div>
      </div>

      {/* Info rows */}
      <div className="rounded-md border border-border/40 px-3 py-1">
        <InfoRow label="重原子数" value={data.heavy_atom_count} />
        <InfoRow label="总原子数（含H）" value={data.atom_count} />
      </div>

      {/* Output preview */}
      <ContentPreview content={data.output} label="输出内容" />

      {/* Actions */}
      <div className="flex gap-2">
        <Button size="sm" variant="outline" className="flex-1 text-xs h-8" onClick={handleCopy}>
          <Copy className="h-3.5 w-3.5 mr-1.5" />
          {copied ? '已复制！' : '复制'}
        </Button>
        <Button
          size="sm"
          className="flex-1 text-xs h-8"
          onClick={() => triggerDownload(data.output, filename, mimeType)}
        >
          <Download className="h-3.5 w-3.5 mr-1.5" />
          下载 .{ext}
        </Button>
      </div>
    </div>
  )
}

// ── Tool 2: 3D Conformer ──────────────────────────────────────────────────────

function Conformer3DCard({ data }: { data: Conformer3DResult }) {
  const filename = data.name ? `${data.name}_3d.sdf` : 'molecule_3d.sdf'

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border/60 bg-card p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          <span className="text-sm font-semibold">
            {data.name ? data.name : '3D 构象'} — 生成成功
          </span>
        </div>
        <Badge variant="outline" className="text-[10px] py-0 px-1.5 font-mono uppercase">
          SDF
        </Badge>
      </div>

      {/* 3D check */}
      {!data.has_3d_coords && (
        <div className="flex items-center gap-1.5 text-xs text-amber-600 bg-amber-50 rounded-md px-3 py-2 border border-amber-200">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          Z 坐标全为零，3D 生成可能未完全成功，请检查分子结构。
        </div>
      )}

      {/* Info rows */}
      <div className="rounded-md border border-border/40 px-3 py-1">
        <InfoRow label="力场" value={<span className="font-mono uppercase">{data.forcefield}</span>} />
        <InfoRow label="优化步数" value={data.steps} />
        <InfoRow label="重原子数" value={data.heavy_atom_count} />
        <InfoRow label="总原子数（含H）" value={data.atom_count} />
        <InfoRow
          label="3D 坐标"
          value={
            data.has_3d_coords ? (
              <span className="text-green-600">✓ 正常</span>
            ) : (
              <span className="text-amber-500">⚠ 异常</span>
            )
          }
        />
      </div>

      {/* SDF preview */}
      <ContentPreview content={data.sdf_content} label="SDF 内容" />

      {/* Download */}
      <Button
        size="sm"
        className="w-full text-xs h-8"
        onClick={() => triggerDownload(data.sdf_content, filename, 'chemical/x-mdl-sdfile')}
      >
        <Download className="h-3.5 w-3.5 mr-1.5" />
        下载 {filename}
      </Button>
    </div>
  )
}

// ── Tool 3: PDBQT Docking Prep ────────────────────────────────────────────────

function PdbqtPrepCard({ data }: { data: PdbqtPrepResult }) {
  const filename = data.name ? `${data.name}_docking.pdbqt` : 'molecule_docking.pdbqt'

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border/60 bg-card p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          <span className="text-sm font-semibold">
            {data.name ? data.name : '配体'} — 对接文件就绪
          </span>
        </div>
        <Badge variant="outline" className="text-[10px] py-0 px-1.5 font-mono uppercase">
          PDBQT
        </Badge>
      </div>

      {/* Flexibility warning */}
      {data.flexibility_warning && (
        <div className="flex items-start gap-1.5 text-xs text-amber-700 bg-amber-50 rounded-md px-3 py-2 border border-amber-200">
          <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            可旋转键 {data.rotatable_bonds} 个，超过 Vina/Smina 推荐上限（10）。
            搜索空间将指数级增大，建议预先对构象进行约束。
          </span>
        </div>
      )}

      {/* Format integrity */}
      {(!data.has_root_marker || !data.has_torsdof_marker) && (
        <div className="flex items-start gap-1.5 text-xs text-red-700 bg-red-50 rounded-md px-3 py-2 border border-red-200">
          <XCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            PDBQT 缺少必需标记（ROOT / TORSDOF），文件可能不完整，
            请检查分子结构后重试。
          </span>
        </div>
      )}

      {/* Info rows */}
      <div className="rounded-md border border-border/40 px-3 py-1">
        <InfoRow label="质子化 pH" value={data.ph.toFixed(1)} />
        <InfoRow
          label="可旋转键数"
          value={
            <span className={data.rotatable_bonds > 10 ? 'text-amber-600 font-semibold' : ''}>
              {data.rotatable_bonds}
              {data.rotatable_bonds > 10 ? ' ⚠' : ''}
            </span>
          }
        />
        <InfoRow label="重原子数" value={data.heavy_atom_count} />
        <InfoRow label="总原子数（含H）" value={data.total_atom_count} />
        <InfoRow
          label="ROOT / TORSDOF"
          value={
            data.has_root_marker && data.has_torsdof_marker ? (
              <span className="text-green-600">✓ 完整</span>
            ) : (
              <span className="text-red-500">✗ 缺失</span>
            )
          }
        />
      </div>

      {/* PDBQT preview */}
      <ContentPreview content={data.pdbqt_content} label="PDBQT 内容" />

      {/* Download */}
      <Button
        size="sm"
        className="w-full text-xs h-8"
        onClick={() =>
          triggerDownload(data.pdbqt_content, filename, 'chemical/x-pdbqt')
        }
      >
        <Download className="h-3.5 w-3.5 mr-1.5" />
        下载 {filename}
      </Button>
    </div>
  )
}

// ── Main discriminated renderer ───────────────────────────────────────────────

export function BabelResultCard({ data }: { data: BabelResponse }) {
  if (!data.is_valid) {
    return <BabelErrorCard error={(data as BabelError).error} />
  }

  const result = data as BabelResult

  switch (result.type) {
    case 'format_conversion':
      return <FormatConversionCard data={result} />
    case 'conformer_3d':
      return <Conformer3DCard data={result} />
    case 'pdbqt_prep':
      return <PdbqtPrepCard data={result} />
    default:
      return null
  }
}

'use client'

import { useState, useRef, useCallback, type DragEvent } from 'react'
import { XCircle, Upload, Download, FileStack, RotateCcw, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  sdfSplit, sdfMerge,
  getSdfSplitDownloadUrl, getSdfMergeDownloadUrl,
  type SdfSplitResult, type SdfMergeResult, type ChemError,
} from '@/lib/chem-api'
import { ResultCard, InfoRow } from './ToolLayout'
import { NetworkErrorAlert } from '../shared'

type Mode = 'split' | 'merge'

export function SdfBatchTool() {
  const [mode, setMode] = useState<Mode>('split')
  const [files, setFiles] = useState<File[]>([])
  const [splitResult, setSplitResult] = useState<SdfSplitResult | null>(null)
  const [mergeResult, setMergeResult] = useState<SdfMergeResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)

  function switchMode(m: Mode) {
    setMode(m); setFiles([]); setSplitResult(null); setMergeResult(null); setError(null)
  }

  function handleFiles(fileList: FileList | File[]) {
    const arr = Array.from(fileList).filter(f => f.name.toLowerCase().endsWith('.sdf'))
    if (arr.length === 0) {
      setError('请上传 .sdf 格式的文件。')
      return
    }
    if (mode === 'split' && arr.length > 1) {
      setFiles([arr[0]])
    } else {
      setFiles(arr)
    }
    setError(null); setSplitResult(null); setMergeResult(null)
  }

  const onDrop = useCallback((e: DragEvent) => {
    e.preventDefault(); setIsDragging(false)
    if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files)
  }, [mode])

  const onDragOver = useCallback((e: DragEvent) => { e.preventDefault(); setIsDragging(true) }, [])
  const onDragLeave = useCallback(() => setIsDragging(false), [])

  async function execute() {
    if (files.length === 0) return
    setLoading(true); setError(null); setSplitResult(null); setMergeResult(null)
    try {
      if (mode === 'split') {
        const res = await sdfSplit(files[0])
        if (!res.is_valid) setError((res as ChemError).error)
        else setSplitResult(res as SdfSplitResult)
      } else {
        const res = await sdfMerge(files)
        if (!res.is_valid) setError((res as ChemError).error)
        else setMergeResult(res as SdfMergeResult)
      }
    } catch (err: any) {
      setError(err.message || '处理失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Mode selector */}
      <div className="flex gap-2">
        <button
          onClick={() => switchMode('split')}
          className={`flex-1 flex items-center justify-center gap-1.5 rounded-lg border py-2 text-sm font-medium transition-colors ${
            mode === 'split'
              ? 'bg-primary text-primary-foreground border-primary'
              : 'bg-background text-muted-foreground hover:bg-muted border-border'
          }`}
        >
          <FileStack className="h-4 w-4" /> 拆分 (Split)
        </button>
        <button
          onClick={() => switchMode('merge')}
          className={`flex-1 flex items-center justify-center gap-1.5 rounded-lg border py-2 text-sm font-medium transition-colors ${
            mode === 'merge'
              ? 'bg-primary text-primary-foreground border-primary'
              : 'bg-background text-muted-foreground hover:bg-muted border-border'
          }`}
        >
          <RotateCcw className="h-4 w-4" /> 合并 (Merge)
        </button>
      </div>

      <div className="text-[11px] text-muted-foreground bg-muted/40 rounded-md px-3 py-2 leading-relaxed">
        {mode === 'split'
          ? '上传 1 个多分子 .sdf 文件，系统将逐一拆分为独立 SDF 并打包为 ZIP 下载。'
          : '上传多个 .sdf 文件，系统将合并为一个统一的 SDF 库文件。'}
      </div>

      {/* Dropzone */}
      <div
        onClick={() => inputRef.current?.click()}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        className={`relative flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed py-8 cursor-pointer transition-colors ${
          isDragging
            ? 'border-primary bg-primary/5'
            : 'border-border hover:border-primary/50 hover:bg-muted/30'
        }`}
      >
        <Upload className={`h-8 w-8 ${isDragging ? 'text-primary' : 'text-muted-foreground'}`} />
        <p className="text-sm text-muted-foreground">
          {isDragging
            ? '松开以上传'
            : mode === 'split'
              ? '点击或拖拽上传 1 个 .sdf 文件'
              : '点击或拖拽上传多个 .sdf 文件'}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".sdf"
          multiple={mode === 'merge'}
          className="hidden"
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {files.map((f, i) => (
            <Badge key={i} variant="outline" className="text-[10px] font-mono">
              {f.name} ({(f.size / 1024).toFixed(1)} KB)
            </Badge>
          ))}
        </div>
      )}

      <Button onClick={execute} disabled={loading || files.length === 0} className="w-full">
        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {loading ? '处理中...' : mode === 'split' ? '执行拆分' : '执行合并'}
      </Button>

      {error && <NetworkErrorAlert message={error} />}

      {/* Split result */}
      {splitResult && (
        <ResultCard>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <FileStack className="h-4 w-4 text-green-500" />
              <span className="text-sm font-semibold">拆分完成</span>
            </div>
            <Badge className="text-[10px] bg-green-100 text-green-700 border-green-200">
              {splitResult.molecule_count} 个分子
            </Badge>
          </div>

          {splitResult.molecules.length > 0 && (
            <div className="max-h-[200px] overflow-y-auto rounded-md border border-border/40">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-muted/80 backdrop-blur-sm">
                  <tr>
                    <th className="text-left px-3 py-1 font-medium text-muted-foreground">#</th>
                    <th className="text-left px-3 py-1 font-medium text-muted-foreground">名称</th>
                    <th className="text-left px-3 py-1 font-medium text-muted-foreground">SMILES</th>
                  </tr>
                </thead>
                <tbody>
                  {splitResult.molecules.map((m) => (
                    <tr key={m.index} className="border-b border-border/30 last:border-0">
                      <td className="px-3 py-1 tabular-nums text-muted-foreground">{m.index + 1}</td>
                      <td className="px-3 py-1">{m.name}</td>
                      <td className="px-3 py-1 font-mono text-[10px] text-muted-foreground truncate max-w-[200px]">{m.smiles}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <a href={getSdfSplitDownloadUrl()} download>
            <Button className="w-full" variant="outline">
              <Download className="mr-2 h-4 w-4" />
              下载 ZIP ({splitResult.molecule_count} 个 SDF)
            </Button>
          </a>
        </ResultCard>
      )}

      {/* Merge result */}
      {mergeResult && (
        <ResultCard>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <RotateCcw className="h-4 w-4 text-green-500" />
              <span className="text-sm font-semibold">合并完成</span>
            </div>
            <Badge className="text-[10px] bg-green-100 text-green-700 border-green-200">
              {mergeResult.molecule_count} 个分子
            </Badge>
          </div>

          <div className="rounded-md border border-border/40 px-3 py-1">
            <InfoRow label="成功合并" value={`${mergeResult.molecule_count} 个分子`} />
            {mergeResult.error_count > 0 && (
              <InfoRow label="解析失败" value={
                <span className="text-red-500">{mergeResult.error_count} 个</span>
              } />
            )}
          </div>

          <a href={getSdfMergeDownloadUrl()} download>
            <Button className="w-full" variant="outline">
              <Download className="mr-2 h-4 w-4" />
              下载合并后 SDF
            </Button>
          </a>
        </ResultCard>
      )}
    </div>
  )
}

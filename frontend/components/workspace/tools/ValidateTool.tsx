'use client'

import { useState } from 'react'
import { CheckCircle2, XCircle, Hash } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { useMutation } from '@tanstack/react-query'
import { validateSmiles, type ValidateResponse } from '@/lib/chem-api'
import { ToolLayout, InfoRow, ResultCard } from './ToolLayout'
import { ResultSkeleton } from './ResultSkeleton'

export function ValidateTool() {
  const { currentSmiles } = useWorkspaceStore()

  const mutation = useMutation({
    mutationFn: (smiles: string) => validateSmiles(smiles),
  })

  function execute() {
    if (!currentSmiles.trim()) return
    mutation.mutate(currentSmiles.trim())
  }

  return (
    <ToolLayout
      title="SMILES 验证与规范化"
      buttonLabel="验证 SMILES"
      loadingLabel="正在验证..."
      onExecute={execute}
      loading={mutation.isPending}
      error={mutation.error ? (mutation.error as Error).message : null}
      resultSlot={
        mutation.isPending ? (
          <ResultSkeleton type="default" />
        ) : mutation.data ? (
          <ValidateResultCard data={mutation.data} />
        ) : null
      }
    />
  )
}

function ValidateResultCard({ data }: { data: ValidateResponse }) {
  if (!data.is_valid) {
    return (
      <ResultCard>
        <div className="flex items-center gap-2">
          <XCircle className="h-4 w-4 text-red-500" />
          <span className="text-sm font-semibold text-red-700">SMILES 无效</span>
        </div>
        <p className="text-xs text-red-600">{data.error}</p>
      </ResultCard>
    )
  }

  return (
    <ResultCard>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          <span className="text-sm font-semibold">SMILES 合法</span>
        </div>
        {data.is_canonical ? (
          <Badge className="text-[10px] bg-green-100 text-green-700 border-green-200">已规范化</Badge>
        ) : (
          <Badge variant="outline" className="text-[10px]">已重新规范化</Badge>
        )}
      </div>

      <div className="rounded-md bg-muted/50 px-3 py-2">
        <p className="text-[10px] text-muted-foreground mb-1">规范 SMILES</p>
        <p className="text-xs font-mono break-all select-all">{data.canonical_smiles}</p>
      </div>

      <div className="rounded-md border border-border/40 px-3 py-1">
        <InfoRow label="分子式" value={data.formula} />
        <InfoRow label="重原子数" value={data.heavy_atom_count} />
        <InfoRow label="总原子数" value={data.atom_count} />
        <InfoRow label="化学键数" value={data.bond_count} />
        <InfoRow label="环数" value={data.ring_count} />
      </div>
    </ResultCard>
  )
}

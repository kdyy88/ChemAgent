'use client'

import { useState, type ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { ExampleChips, FieldLabel, NetworkErrorAlert } from '../shared'

/**
 * Shared layout wrapper for all chemistry tool forms.
 * Encapsulates: SMILES input, example chips, loading state, error display.
 *
 * Tools only need to provide:
 *   - extra form fields (via `children`)
 *   - result rendering (via `resultSlot`)
 *   - the execute function
 */
export function ToolLayout({
  title,
  description,
  buttonLabel,
  loadingLabel,
  showNameField = false,
  showSmilesInput = true,
  smilesLabel = 'SMILES',
  smilesPlaceholder = 'CC(=O)Oc1ccccc1C(=O)O',
  children,
  resultSlot,
  onExecute,
  loading,
  error,
  disabled = false,
}: {
  title: string
  description?: string
  buttonLabel: string
  loadingLabel: string
  showNameField?: boolean
  showSmilesInput?: boolean
  smilesLabel?: string
  smilesPlaceholder?: string
  children?: ReactNode
  resultSlot?: ReactNode
  onExecute: () => void
  loading: boolean
  error: string | null
  disabled?: boolean
}) {
  const { currentSmiles, setSmiles } = useWorkspaceStore()

  return (
    <div className="flex flex-col gap-4">
      <ExampleChips onSelect={(s) => { setSmiles(s) }} />

      {showSmilesInput && (
        <div>
          <FieldLabel required>{smilesLabel}</FieldLabel>
          <Textarea
            value={currentSmiles}
            onChange={(e) => setSmiles(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault()
                onExecute()
              }
            }}
            placeholder={smilesPlaceholder}
            className="font-mono text-sm resize-none min-h-[80px]"
          />
          <p className="text-[10px] text-muted-foreground/70 mt-1">Ctrl/⌘ + Enter 快速提交</p>
        </div>
      )}

      {description && (
        <div className="text-[11px] text-muted-foreground bg-muted/40 rounded-md px-3 py-2 leading-relaxed">
          {description}
        </div>
      )}

      {children}

      <Button
        onClick={onExecute}
        disabled={loading || disabled || (!showSmilesInput ? false : !currentSmiles.trim())}
        className="w-full"
      >
        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {loading ? loadingLabel : buttonLabel}
      </Button>

      {error && <NetworkErrorAlert message={error} />}
      {resultSlot}
    </div>
  )
}

/**
 * Reusable info row for result cards.
 */
export function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xs font-medium">{value}</span>
    </div>
  )
}

/**
 * Reusable info card container.
 */
export function ResultCard({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col gap-3 rounded-lg border border-border/60 bg-card p-4 ${className}`}>
      {children}
    </div>
  )
}

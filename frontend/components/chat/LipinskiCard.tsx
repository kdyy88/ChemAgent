'use client'

import { AlertTriangle, CheckCircle2, XCircle, FlaskConical } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { LipinskiResponse, LipinskiResult, LipinskiProperty } from '@/lib/chem-api'

// ── Property row ──────────────────────────────────────────────────────────────

const PROPERTY_LABELS: Record<string, string> = {
  molecular_weight: '分子量',
  log_p: '脂水分配系数 LogP',
  h_bond_donors: '氢键供体 HBD',
  h_bond_acceptors: '氢键受体 HBA',
}

const PROPERTY_UNITS: Record<string, string> = {
  molecular_weight: 'Da',
  log_p: '',
  h_bond_donors: '',
  h_bond_acceptors: '',
}

function PropertyRow({
  label,
  prop,
  unit = '',
  isReference = false,
}: {
  label: string
  prop: LipinskiProperty
  unit?: string
  isReference?: boolean
}) {
  const displayValue =
    Number.isInteger(prop.value)
      ? prop.value.toString()
      : prop.value.toFixed(2)

  return (
    <tr className={isReference ? 'opacity-60' : ''}>
      <td className="py-1.5 pr-4 text-sm text-muted-foreground whitespace-nowrap">{label}</td>
      <td className="py-1.5 pr-4 text-sm font-mono font-medium tabular-nums">
        {displayValue}
        {unit && <span className="ml-1 text-xs text-muted-foreground">{unit}</span>}
      </td>
      <td className="py-1.5 pr-4 text-xs text-muted-foreground whitespace-nowrap">
        {prop.threshold !== undefined ? `≤ ${prop.threshold}` : ''}
      </td>
      <td className="py-1.5 text-right">
        {isReference ? (
          <span className="text-[10px] text-muted-foreground italic">参考值</span>
        ) : prop.pass ? (
          <CheckCircle2 className="inline h-4 w-4 text-emerald-500" />
        ) : (
          <XCircle className="inline h-4 w-4 text-red-500" />
        )}
      </td>
    </tr>
  )
}

// ── Error state ───────────────────────────────────────────────────────────────

function LipinskiErrorCard({ error }: { error: string }) {
  return (
    <Card className="border-red-200 bg-red-50/60 shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          SMILES 解析失败
        </CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-red-700/90">
        <p className="mb-1">{error}</p>
        <p className="text-xs text-red-600/70">
          提示：请检查环闭合、括号匹配、芳香性标记与原子价态后重试。
        </p>
      </CardContent>
    </Card>
  )
}

// ── Success state ─────────────────────────────────────────────────────────────

function LipinskiSuccessCard({ data }: { data: LipinskiResult }) {
  const { properties, lipinski_pass, violations } = data
  const lipinski_props = [
    'molecular_weight',
    'log_p',
    'h_bond_donors',
    'h_bond_acceptors',
  ] as const

  return (
    <Card className="shadow-sm overflow-hidden">
      <CardHeader className="pb-2 bg-muted/30">
        <CardTitle className="flex items-center gap-2 text-sm">
          <FlaskConical className="h-4 w-4 text-primary shrink-0" />
          <span className="truncate font-semibold">
            {data.name || 'Unnamed Molecule'}
          </span>
          {lipinski_pass ? (
            <Badge className="ml-auto shrink-0 text-[10px] bg-emerald-100 text-emerald-700 border-emerald-200 hover:bg-emerald-100">
              通过 Lipinski 五规则
            </Badge>
          ) : (
            <Badge className="ml-auto shrink-0 text-[10px] bg-red-100 text-red-700 border-red-200 hover:bg-red-100">
              {violations} 条违规
            </Badge>
          )}
        </CardTitle>
        <p className="text-[10px] font-mono text-muted-foreground break-all leading-relaxed mt-0.5">
          {data.smiles}
        </p>
      </CardHeader>

      <CardContent className="pt-3 pb-0 flex flex-col gap-3 sm:flex-row sm:items-start">
        {/* 2D structure image — prefix added here and ONLY here */}
        <img
          src={`data:image/png;base64,${data.structure_image}`}
          alt={data.name || data.smiles}
          width={160}
          height={160}
          className="rounded-md border bg-white object-contain shrink-0 self-center sm:self-start"
        />

        {/* Descriptor table */}
        <div className="overflow-x-auto w-full">
          <table className="w-full border-separate border-spacing-0">
            <thead>
              <tr>
                <th className="text-left text-[10px] text-muted-foreground font-medium pb-1.5">参数</th>
                <th className="text-left text-[10px] text-muted-foreground font-medium pb-1.5">数值</th>
                <th className="text-left text-[10px] text-muted-foreground font-medium pb-1.5">阈值</th>
                <th className="text-right text-[10px] text-muted-foreground font-medium pb-1.5">结果</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {lipinski_props.map((key) => (
                <PropertyRow
                  key={key}
                  label={PROPERTY_LABELS[key]}
                  prop={properties[key]}
                  unit={PROPERTY_UNITS[key]}
                />
              ))}
              {/* TPSA — display only, no badge */}
              <PropertyRow
                label="极性表面积 TPSA"
                prop={properties.tpsa}
                unit={properties.tpsa.unit}
                isReference
              />
            </tbody>
          </table>
        </div>
      </CardContent>

      <CardFooter className="pt-3 pb-3">
        <p className="text-xs text-muted-foreground">
          {lipinski_pass
            ? '✅ 符合 Lipinski 五规则（MW，LogP，HBD，HBA），具备良好的口服生物利用度潜力。'
            : `⚠️ 存在 ${violations} 条 Lipinski 违规，口服生物利用度可能受限（违规化合物不一定无效）。`}
          <span className="block mt-0.5 opacity-60">TPSA 为参考值，不计入五规则评分。</span>
        </p>
      </CardFooter>
    </Card>
  )
}

// ── Public component ──────────────────────────────────────────────────────────

/**
 * Renders a Lipinski Rule-of-5 analysis card.
 *
 * Accepts either a `LipinskiResult` (successful analysis) or a `LipinskiError`
 * (failed SMILES parse). Both branches are handled gracefully — no white-screen
 * crashes on bad input.
 *
 * The `data:image/png;base64,` URI prefix is added here in JSX.
 * The backend always returns `structure_image` as a bare base64 string.
 */
export function LipinskiCard({ data }: { data: LipinskiResponse }) {
  if (!data.is_valid) {
    return <LipinskiErrorCard error={data.error} />
  }
  return <LipinskiSuccessCard data={data} />
}

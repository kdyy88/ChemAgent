'use client'

import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'
import { AlertTriangle, CheckCircle2, FlaskConical, XCircle } from 'lucide-react'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { LipinskiResponse, LipinskiResult } from '@/lib/chem-api'

// ── Axis config ───────────────────────────────────────────────────────────────

const AXES = [
  { key: 'molecular_weight', label: 'MW 分子量',  threshold: 500 },
  { key: 'log_p',            label: 'LogP',      threshold: 5 },
  { key: 'h_bond_donors',    label: 'HBD 供体',  threshold: 5 },
  { key: 'h_bond_acceptors', label: 'HBA 受体',  threshold: 10 },
  { key: 'tpsa',             label: 'TPSA 极性', threshold: 140 },
] as const

type AxisKey = (typeof AXES)[number]['key']

function buildRadarData(data: LipinskiResult) {
  const props = data.properties as Record<string, { value: number }>
  return AXES.map(({ key, label, threshold }) => {
    const raw = props[key]?.value ?? 0
    // Normalise: 1.0 = exactly at threshold. Cap display at 1.5 so no axis is blown out.
    const normalised = Math.min(raw / threshold, 1.5)
    return { axis: label, value: parseFloat(normalised.toFixed(3)), raw, threshold }
  })
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { payload: { axis: string; raw: number; threshold: number } }[] }) {
  if (!active || !payload?.length) return null
  const { axis, raw, threshold } = payload[0].payload
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-lg">
      <p className="font-semibold mb-0.5">{axis}</p>
      <p>值：<span className="font-mono">{raw.toFixed(2)}</span></p>
      <p className="text-muted-foreground">阈值：{threshold}</p>
    </div>
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

function LipinskiRadarCardSuccess({ data }: { data: LipinskiResult }) {
  const { lipinski_pass, violations } = data
  const radarData = buildRadarData(data)

  return (
    <Card className="shadow-sm overflow-hidden w-full max-w-[420px]">
      <CardHeader className="pb-2 bg-muted/30">
        <CardTitle className="flex items-center gap-2 text-sm">
          <FlaskConical className="h-4 w-4 text-primary shrink-0" />
          <span className="truncate font-semibold">
            {data.name || 'Unnamed Molecule'}
          </span>
          {lipinski_pass ? (
            <Badge className="ml-auto shrink-0 text-[10px] bg-emerald-100 text-emerald-700 border-emerald-200 hover:bg-emerald-100">
              <CheckCircle2 className="h-3 w-3 mr-1" />
              Lipinski Pass
            </Badge>
          ) : (
            <Badge className="ml-auto shrink-0 text-[10px] bg-red-100 text-red-700 border-red-200 hover:bg-red-100">
              <XCircle className="h-3 w-3 mr-1" />
              {violations} 条违规
            </Badge>
          )}
        </CardTitle>
        <p className="text-[10px] font-mono text-muted-foreground break-all leading-relaxed mt-0.5">
          {data.smiles}
        </p>
      </CardHeader>

      <CardContent className="pt-3 pb-0 flex flex-col items-center gap-3 sm:flex-row sm:items-start">
        {/* 2D structure image */}
        <img
          src={`data:image/png;base64,${data.structure_image}`}
          alt={data.name || data.smiles}
          width={130}
          height={130}
          className="rounded-md border bg-white object-contain shrink-0 self-center sm:self-start"
        />

        {/* Radar chart */}
        <div className="w-full h-[180px]">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={radarData} outerRadius="72%">
              <PolarGrid stroke="hsl(var(--border))" />
              <PolarAngleAxis
                dataKey="axis"
                tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
              />
              <Radar
                dataKey="value"
                stroke="hsl(var(--primary))"
                fill="hsl(var(--primary))"
                fillOpacity={0.3}
                strokeWidth={1.5}
              />
              <Tooltip content={<CustomTooltip />} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>

      <CardFooter className="pt-3 pb-3">
        <p className="text-xs text-muted-foreground">
          {lipinski_pass
            ? '✅ 符合 Lipinski 五规则（MW，LogP，HBD，HBA），具备良好的口服生物利用度潜力。'
            : `⚠️ 存在 ${violations} 条 Lipinski 违规，口服生物利用度可能受限。`}
          <span className="block mt-0.5 opacity-60">雷达图已归一化（1.0 = 阈值边界），TPSA 为参考值，不计入五规则评分。</span>
        </p>
      </CardFooter>
    </Card>
  )
}

// ── Public export ─────────────────────────────────────────────────────────────

export function LipinskiRadarCard({ data }: { data: LipinskiResponse }) {
  if (!data.is_valid) {
    return <LipinskiErrorCard error={(data as { error: string }).error} />
  }
  return <LipinskiRadarCardSuccess data={data as LipinskiResult} />
}

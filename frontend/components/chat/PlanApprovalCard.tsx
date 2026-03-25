'use client'

import { memo, useState } from 'react'
import { CheckCircle2, XCircle, ChevronDown, ChevronUp, ClipboardList } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface PlanApprovalCardProps {
  plan: string
  status: 'awaiting_approval' | 'thinking' | 'done'
  onApprove: (feedback?: string) => void
  onReject: () => void
}

export const PlanApprovalCard = memo(function PlanApprovalCard({
  plan,
  status,
  onApprove,
  onReject,
}: PlanApprovalCardProps) {
  const [expanded, setExpanded] = useState(true)
  const isAwaiting = status === 'awaiting_approval'

  // Parse plan text: try to extract numbered steps
  const lines = plan
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

  return (
    <Card className={cn(
      'my-2 border transition-colors',
      isAwaiting ? 'border-blue-200 bg-blue-50/50 dark:border-blue-800 dark:bg-blue-950/30' : 'border-muted',
    )}>
      <CardHeader className="py-2 px-3 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-1.5">
            <ClipboardList className="h-4 w-4 text-blue-500" />
            执行计划
          </CardTitle>
          {expanded ? (
            <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="px-3 pb-2 pt-0">
          <div className="text-xs text-foreground/80 space-y-1 font-mono">
            {lines.map((line, i) => (
              <p key={i} className="leading-relaxed">{line}</p>
            ))}
          </div>
        </CardContent>
      )}

      {status !== 'done' && (
        <CardFooter className="px-3 pb-2 pt-0 flex gap-2">
          <Button
            size="sm"
            variant="default"
            className="h-8 text-xs gap-1.5 px-4"
            disabled={!isAwaiting}
            onClick={() => onApprove()}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            {isAwaiting ? '立即执行' : '等待计划完成…'}
          </Button>
          {isAwaiting && (
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-xs gap-1.5 text-red-600 hover:text-red-700"
              onClick={onReject}
            >
              <XCircle className="h-3.5 w-3.5" />
              拒绝
            </Button>
          )}
        </CardFooter>
      )}
    </Card>
  )
})

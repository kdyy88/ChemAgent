'use client'

import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { ConnectionStatus } from '@/store/chatStore'

interface ConnectionStatusBadgeProps {
  status: ConnectionStatus
}

const STATUS_CONFIG: Record<ConnectionStatus, { dot: string; pulse: boolean; label: string }> = {
  connected:     { dot: 'bg-green-500',  pulse: false, label: '已连接' },
  connecting:    { dot: 'bg-gray-400',   pulse: true,  label: '连接中…' },
  reconnecting:  { dot: 'bg-yellow-500', pulse: true,  label: '重连中…' },
  disconnected:  { dot: 'bg-red-500',    pulse: false, label: '已断开' },
}

export const ConnectionStatusBadge = memo(function ConnectionStatusBadge({
  status,
}: ConnectionStatusBadgeProps) {
  const config = STATUS_CONFIG[status]

  return (
    <div className="flex items-center gap-1.5">
      <span className="relative flex h-2 w-2">
        {config.pulse && (
          <span
            className={cn(
              'absolute inline-flex h-full w-full rounded-full opacity-75 animate-ping',
              config.dot,
            )}
          />
        )}
        <span className={cn('relative inline-flex h-2 w-2 rounded-full', config.dot)} />
      </span>
      <span className="text-[10px] text-muted-foreground select-none">{config.label}</span>
    </div>
  )
})

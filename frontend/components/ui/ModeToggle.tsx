'use client'

import { FlaskConical, Bot } from 'lucide-react'
import { motion } from 'framer-motion'
import { useUIStore, type AppMode } from '@/store/uiStore'
import { cn } from '@/lib/utils'

const MODES: { value: AppMode; label: string; Icon: React.ElementType }[] = [
  { value: 'copilot', label: 'Copilot', Icon: FlaskConical },
  { value: 'agent',   label: 'Agent',   Icon: Bot },
]

interface ModeToggleProps {
  /** Modes that are disabled (greyed out, not clickable) */
  disabledModes?: AppMode[]
  /** Tooltip shown on hover for disabled modes */
  disabledTitle?: string
}

export function ModeToggle({ disabledModes = [], disabledTitle = '暂未开放' }: ModeToggleProps) {
  const { appMode, setMode } = useUIStore()

  return (
    <div
      role="group"
      aria-label="Switch application mode"
      className="relative flex h-7 items-center rounded-full border bg-muted/60 p-0.5 gap-0"
    >
      {MODES.map(({ value, label, Icon }) => {
        const active = appMode === value
        const disabled = disabledModes.includes(value)
        return (
          <button
            key={value}
            onClick={() => !disabled && setMode(value)}
            aria-pressed={active}
            aria-label={`${label} mode${disabled ? ' (暂未开放)' : ''}`}
            title={disabled ? disabledTitle : undefined}
            disabled={disabled}
            className={cn(
              'relative z-10 flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium transition-colors duration-200',
              disabled
                ? 'cursor-not-allowed opacity-40 text-muted-foreground'
                : active
                  ? 'text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {active && !disabled && (
              <motion.span
                layoutId="mode-pill"
                className="absolute inset-0 rounded-full bg-primary"
                transition={{ type: 'spring', stiffness: 400, damping: 30 }}
              />
            )}
            <Icon className="relative h-3 w-3 shrink-0" aria-hidden="true" />
            <span className="relative hidden sm:inline">{label}</span>

          </button>
        )
      })}
    </div>
  )
}

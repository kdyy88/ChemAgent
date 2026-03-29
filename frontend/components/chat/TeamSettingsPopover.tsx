'use client'

import { useState } from 'react'
import { Settings2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { useSseStore } from '@/store/sseStore'
import { useSettingsStore } from '@/store/settingsStore'
import type { AgentModelConfig } from '@/lib/types'

// ── Model catalogue ───────────────────────────────────────────────────────────
// Only includes models that fully support system prompts + tool calling.
// O-series (o1, o3) are intentionally excluded — they have incompatible
// system-prompt and tool-calling semantics with the AG2 framework used here.
const MODEL_OPTIONS: { label: string; value: string }[] = [
  { label: 'GPT-4o', value: 'gpt-4o' },
  { label: 'GPT-4o mini', value: 'gpt-4o-mini' },
  { label: 'GPT-5 mini', value: 'gpt-5-mini' },
  { label: 'GPT-5 nano', value: 'gpt-5-nano' },
  { label: 'GPT-4.1 nano', value: 'gpt-4.1-nano' },
]

const DEFAULT_MODEL = 'gpt-4o-mini'

// ── Agent rows config ─────────────────────────────────────────────────────────
const AGENTS: { key: keyof AgentModelConfig; icon: string; label: string }[] = [
  { key: 'manager',    icon: '🧠', label: 'Manager' },
  { key: 'visualizer', icon: '🔬', label: 'Visualizer' },
  { key: 'researcher', icon: '📚', label: 'Researcher' },
]

// ── Component ─────────────────────────────────────────────────────────────────
export function TeamSettingsPopover() {
  const turns = useSseStore((s) => s.turns)
  const clearTurns = useSseStore((s) => s.clearTurns)
  const { agentModels, setAgentModels } = useSettingsStore()
  const isLocked = turns.length > 0

  // Pending change waiting for user confirmation (only used when isLocked)
  const [pending, setPending] = useState<{ key: keyof AgentModelConfig; value: string } | null>(null)

  function handleChange(key: keyof AgentModelConfig, value: string) {
    if (value === (agentModels[key] ?? DEFAULT_MODEL)) return
    if (isLocked) {
      // Ask before blowing away the current conversation
      setPending({ key, value })
    } else {
      setAgentModels({ ...agentModels, [key]: value })
    }
  }

  function confirmChange() {
    if (!pending) return
    const next = { ...agentModels, [pending.key]: pending.value }
    setAgentModels(next)
    clearTurns()
    setPending(null)
  }

  return (
    <>
      <Popover>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground hover:text-foreground">
            <Settings2 className="h-4 w-4" />
            <span className="hidden sm:inline text-xs">Team Settings</span>
          </Button>
        </PopoverTrigger>

        <PopoverContent align="end" className="w-72 p-0">
          {/* Header */}
          <div className="px-4 py-3 border-b">
            <p className="text-sm font-semibold">Team Settings</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Assign a model to each specialist agent
            </p>
          </div>

          {/* Agent rows — always interactive */}
          <div className="px-4 py-3 flex flex-col gap-3">
            {AGENTS.map(({ key, icon, label }) => (
              <div key={key} className="flex items-center justify-between gap-3">
                <span className="text-sm whitespace-nowrap">
                  {icon} <span className="text-muted-foreground">{label}</span>
                </span>
                <Select
                  value={agentModels[key] ?? DEFAULT_MODEL}
                  onValueChange={(v) => handleChange(key, v)}
                >
                  <SelectTrigger className="h-8 w-40 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MODEL_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value} className="text-xs">
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ))}
          </div>

          <Separator />

          {/* Footer hint */}
          <p className="px-4 py-2.5 text-[11px] text-muted-foreground">
            {isLocked
              ? 'Switching models mid-conversation starts a new chat.'
              : 'Settings are applied when the session starts.'}
          </p>
        </PopoverContent>
      </Popover>

      {/* Confirmation dialog — shown when user changes a model mid-conversation */}
      <Dialog open={!!pending} onOpenChange={(open) => { if (!open) setPending(null) }}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>切换模型</DialogTitle>
            <DialogDescription>
              切换模型需要开启新对话，当前会话的对话记录将被清空。是否继续？
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setPending(null)}>
              取消
            </Button>
            <Button onClick={confirmChange}>
              确认并开启新对话
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

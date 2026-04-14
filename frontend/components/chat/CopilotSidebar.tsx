'use client'

import { useTranslation } from 'react-i18next'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowUpRight, Box, FlaskConical, Network, Shuffle, ShieldAlert, Trash2 } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useSSEChemAgent } from '@/hooks/useSSEChemAgent'
import { ModeToggle } from '@/components/ui/ModeToggle'
import { SSEMessageList } from './SSEMessageList'
import { SSEChatInput } from './SSEChatInput'
import { TaskTracker } from './TaskTracker'
import '@/lib/i18n/client'

// ── Motion variants ───────────────────────────────────────────────────────────
const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08, delayChildren: 0.05 } },
}

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, ease: [0.23, 1, 0.32, 1] as [number, number, number, number] },
  },
}

// ── Starter prompt icon map ───────────────────────────────────────────────────
const STARTER_ICONS: LucideIcon[] = [Shuffle, Network, Box, ShieldAlert]

export function CopilotSidebar() {
  const { t } = useTranslation('common')
  const { turns, isStreaming, sendMessage, clearTurns } = useSSEChemAgent()
  const latestTasks = turns.at(-1)?.tasks ?? []

  const starterPrompts = [
    { title: t('copilot.starters.compare.title'), description: t('copilot.starters.compare.description'), prompt: t('copilot.starters.compare.prompt'), Icon: STARTER_ICONS[0] },
    { title: t('copilot.starters.properties.title'), description: t('copilot.starters.properties.description'), prompt: t('copilot.starters.properties.prompt'), Icon: STARTER_ICONS[1] },
    { title: t('copilot.starters.rules.title'), description: t('copilot.starters.rules.description'), prompt: t('copilot.starters.rules.prompt'), Icon: STARTER_ICONS[2] },
    { title: t('copilot.starters.workflow.title'), description: t('copilot.starters.workflow.description'), prompt: t('copilot.starters.workflow.prompt'), Icon: STARTER_ICONS[3] },
  ]

  const capabilities = [
    t('copilot.copilot_capability_1'),
    t('copilot.copilot_capability_2'),
    t('copilot.copilot_capability_3'),
  ]

  const handleStarterClick = async (prompt: string) => {
    if (isStreaming) return
    await sendMessage(prompt)
  }

  return (
    <div className="relative flex h-full flex-col bg-background/50">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <header className="shrink-0 flex items-center gap-2.5 px-4 h-11 border-b border-border/70 bg-transparent">
        {/* Brand mark */}
        <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-primary/10 border border-primary/15">
          <FlaskConical className="h-3 w-3 text-primary" aria-hidden />
        </div>
        <span
          className="font-semibold text-foreground"
          style={{ fontSize: 13, letterSpacing: '-0.02em' }}
        >
          ChemAgent
        </span>
        <ModeToggle disabledModes={['agent']} />

        {/* Right cluster */}
        <div className="ml-auto flex items-center gap-2">
          {/* Turn counter — Notion pill badge */}
          <AnimatePresence>
            {turns.length > 0 && (
              <motion.span
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={{ duration: 0.15 }}
                className="inline-flex items-center rounded-md bg-primary/10 px-2 py-0.5 text-[11px] font-semibold tabular-nums text-primary border border-primary/15"
                style={{ letterSpacing: '0.02em' }}
              >
                {t('copilot.turns', { count: turns.length })}
              </motion.span>
            )}
          </AnimatePresence>

          {/* Clear — ghost icon with micro-animation */}
          <motion.button
            type="button"
            onClick={clearTurns}
            disabled={isStreaming || turns.length === 0}
            title={t('copilot.clear_history')}
            aria-label={t('copilot.clear_history')}
            className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/50 transition-colors hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/40 dark:hover:text-red-400 disabled:pointer-events-none disabled:opacity-25"
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.88 }}
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden />
          </motion.button>
        </div>
      </header>

      {/* ── Message area ─────────────────────────────────────────────────────── */}
      <div className="min-h-0 flex-1 overflow-hidden">

        {turns.length === 0 ? (
          /* ── Empty / welcome state ── */
          <div className="h-full overflow-y-auto">
            <div className="flex min-h-full items-center justify-center">
              <motion.div
                className="w-full max-w-[312px] px-4 py-10 flex flex-col gap-6"
                variants={containerVariants}
                initial="hidden"
                animate="visible"
              >
                {/* ── Hero cluster ── */}
                <motion.div variants={itemVariants} className="flex flex-col items-center gap-4 text-center">
                  <div
                    className="flex h-[52px] w-[52px] items-center justify-center rounded-2xl bg-muted/60"
                    style={{
                      boxShadow:
                        'rgba(0,0,0,0.04) 0px 4px 18px, rgba(0,0,0,0.027) 0px 2.025px 7.85px, rgba(0,0,0,0.02) 0px 0.8px 2.93px, rgba(0,0,0,0.01) 0px 0.175px 1.04px',
                    }}
                  >
                    <FlaskConical className="h-6 w-6 text-primary" aria-hidden />
                  </div>

                  <div className="space-y-1.5">
                    <h2
                      className="font-bold text-foreground"
                      style={{ fontSize: 20, lineHeight: 1.27, letterSpacing: '-0.4px' }}
                    >
                      {t('copilot.empty_title')}
                    </h2>
                    <p className="text-muted-foreground" style={{ fontSize: 13, lineHeight: 1.6 }}>
                      {t('copilot.empty_description')}
                    </p>
                  </div>
                </motion.div>

                {/* ── Capability pills ── */}
                <motion.div variants={itemVariants} className="flex flex-wrap justify-center gap-1.5">
                  {capabilities.map((cap) => (
                    <span
                      key={cap}
                      className="rounded-md bg-primary/10 text-primary"
                      style={{
                        padding: '2px 8px',
                        fontSize: 11,
                        fontWeight: 600,
                        letterSpacing: '0.02em',
                        border: '1px solid oklch(var(--primary) / 0.20)',
                      }}
                    >
                      {cap}
                    </span>
                  ))}
                </motion.div>

                {/* ── Section divider with label ── */}
                <motion.div variants={itemVariants} className="flex items-center gap-3">
                  <div className="h-px flex-1 bg-border/50" />
                  <span
                    className="font-semibold uppercase text-muted-foreground/40"
                    style={{ fontSize: 10, letterSpacing: '0.2em' }}
                  >
                    {t('copilot.starter_label')}
                  </span>
                  <div className="h-px flex-1 bg-border/50" />
                </motion.div>

                {/* ── Prompt cards ── */}
                <div className="flex flex-col gap-2">
                  {starterPrompts.map(({ title, description, prompt, Icon }) => (
                    <motion.button
                      key={title}
                      type="button"
                      variants={itemVariants}
                      disabled={isStreaming}
                      onClick={() => void handleStarterClick(prompt)}
                      className="group w-full rounded-xl bg-background text-left transition-colors disabled:pointer-events-none disabled:opacity-40 border border-border/60 dark:border-border/50"
                      style={{
                        padding: '11px 14px',
                        boxShadow:
                          'rgba(0,0,0,0.04) 0px 4px 18px, rgba(0,0,0,0.027) 0px 2.025px 7.85px, rgba(0,0,0,0.02) 0px 0.8px 2.93px, rgba(0,0,0,0.01) 0px 0.175px 1.04px',
                      }}
                      whileHover={{
                        y: -2,
                        boxShadow:
                          'rgba(0,0,0,0.07) 0px 8px 28px, rgba(0,0,0,0.04) 0px 4px 10px, rgba(0,0,0,0.02) 0px 1.5px 4px',
                      }}
                      whileTap={{ scale: 0.985 }}
                    >
                      <div className="flex items-start gap-3">
                        {/* Category icon */}
                        <div className="mt-px flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-lg bg-muted/60">
                          <Icon className="h-3.5 w-3.5 text-muted-foreground/70" aria-hidden />
                        </div>
                        {/* Text */}
                        <div className="min-w-0 flex-1">
                          <p
                            className="font-semibold text-foreground"
                            style={{ fontSize: 13, lineHeight: 1.4 }}
                          >
                            {title}
                          </p>
                          <p
                            className="mt-0.5 text-muted-foreground"
                            style={{ fontSize: 12, lineHeight: 1.5 }}
                          >
                            {description}
                          </p>
                        </div>
                        {/* Reveal arrow */}
                        <ArrowUpRight
                          className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary opacity-0 transition-opacity group-hover:opacity-100"
                          aria-hidden
                        />
                      </div>
                    </motion.button>
                  ))}
                </div>

                {/* ── Footer hint ── */}
                <motion.p
                  variants={itemVariants}
                  className="text-center text-muted-foreground/40"
                  style={{ fontSize: 11, letterSpacing: '0.1px' }}
                >
                  {t('copilot.starter_hint')}
                </motion.p>
              </motion.div>
            </div>
          </div>
        ) : (
          <SSEMessageList turns={turns} />
        )}
      </div>

      {/* ── Footer ───────────────────────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border/70 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <AnimatePresence initial={false}>
          {latestTasks.length > 0 && (
            <motion.div
              key="task-tracker"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
              className="overflow-hidden px-4 pt-3"
            >
              <TaskTracker tasks={latestTasks} isStreaming={isStreaming} />
            </motion.div>
          )}
        </AnimatePresence>

        <div className="p-3">
          <SSEChatInput isStreaming={isStreaming} sendMessage={sendMessage} />
        </div>
      </div>
    </div>
  )
}

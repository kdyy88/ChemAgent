'use client'

import { useTranslation } from 'react-i18next'
import { motion, type Variants } from 'framer-motion'
import { Beaker, BrainCircuit, Network, ArrowRight } from 'lucide-react'
import '@/lib/i18n/client'

export function HomeLandingPage() {
  const { t } = useTranslation('common')

  const containerVariants: Variants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: { staggerChildren: 0.1, delayChildren: 0.1 },
    },
  }

  const itemVariants: Variants = {
    hidden: { opacity: 0, y: 16 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.25, 0.1, 0.25, 1] } },
  }

  return (
    <div className="relative w-full h-full overflow-hidden flex flex-col items-center justify-center">
      {/* Ambient background glow */}
      <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden="true">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-[480px] w-[480px] rounded-full bg-primary/6 blur-[100px]" />
        <div className="absolute top-[20%] right-[20%] h-[200px] w-[200px] rounded-full bg-primary/4 blur-[70px]" />
      </div>

      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="flex flex-col items-center max-w-3xl px-8 text-center gap-8"
      >
        {/* Mark + badge row */}
        <motion.div variants={itemVariants} className="flex flex-col items-center gap-4">
          {/* Geometric molecular mark */}
          <div className="relative">
            <svg
              className="w-12 h-12 text-primary/50"
              viewBox="0 0 48 48"
              fill="none"
              aria-hidden="true"
            >
              <polygon
                points="24,3 44,15 44,33 24,45 4,33 4,15"
                stroke="currentColor"
                strokeWidth="1"
                strokeLinejoin="round"
                fill="none"
              />
              <polygon
                points="24,11 37,18.5 37,29.5 24,37 11,29.5 11,18.5"
                stroke="currentColor"
                strokeWidth="1"
                strokeLinejoin="round"
                fill="currentColor"
                fillOpacity="0.08"
              />
              <circle cx="24" cy="24" r="3.5" fill="currentColor" fillOpacity="0.6" />
              {[0, 1, 2, 3, 4, 5].map(i => {
                const angle = (i * 60 - 90) * Math.PI / 180
                return (
                  <circle
                    key={i}
                    cx={24 + 13 * Math.cos(angle)}
                    cy={24 + 13 * Math.sin(angle)}
                    r="1.8"
                    fill="currentColor"
                    fillOpacity="0.45"
                  />
                )
              })}
            </svg>
          </div>

          <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/8 px-3 py-1 text-[11px] font-semibold text-primary tracking-[0.04em] uppercase">
            v2.0 · Molecular Workspace Engine
          </span>
        </motion.div>

        {/* Headline */}
        <motion.div variants={itemVariants} className="space-y-3">
          <h1 className="font-display text-4xl md:text-5xl font-bold tracking-[-0.04em] leading-[1.05] text-foreground">
            Chem<span className="text-primary">Agent</span>
            <br />
            <span className="text-foreground/40 font-light tracking-[-0.02em]">Workspace</span>
          </h1>
          <p className="text-[15px] text-muted-foreground leading-relaxed max-w-sm mx-auto">
            {t('home.subtitle')}
          </p>
          <p className="text-[11px] tracking-[0.1em] font-mono text-muted-foreground/40 uppercase">
            {t('home.subtitle_tagline')}
          </p>
        </motion.div>

        {/* Feature cards — horizontal strip */}
        <motion.div
          variants={containerVariants}
          className="grid grid-cols-1 md:grid-cols-3 gap-3 w-full"
        >
          <FeatureCard
            icon={<Beaker className="h-4 w-4" />}
            title={t('home.feature1_title')}
            description={t('home.feature1_desc')}
          />
          <FeatureCard
            icon={<BrainCircuit className="h-4 w-4" />}
            title={t('home.feature2_title')}
            description={t('home.feature2_desc')}
          />
          <FeatureCard
            icon={<Network className="h-4 w-4" />}
            title={t('home.feature3_title')}
            description={t('home.feature3_desc')}
          />
        </motion.div>

        {/* CTA hint */}
        <motion.p variants={itemVariants} className="flex items-center gap-1.5 text-[12px] text-muted-foreground/50 select-none">
          <ArrowRight className="h-3 w-3" aria-hidden="true" />
          从左侧选择工具开始使用，或在右侧面板与 AI 对话
        </motion.p>
      </motion.div>
    </div>
  )
}

function FeatureCard({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 12 },
        visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.25, 0.1, 0.25, 1] } },
      }}
      className="group flex flex-col gap-2.5 p-4 rounded-xl bg-card/70 border border-border/60 hover:border-primary/30 hover:bg-card/90 transition-all duration-200 text-left"
    >
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary group-hover:bg-primary/15 transition-colors duration-200">
        {icon}
      </div>
      <div>
        <h3 className="text-[13px] font-semibold text-foreground leading-snug mb-1">{title}</h3>
        <p className="text-[12px] text-muted-foreground leading-relaxed">{description}</p>
      </div>
    </motion.div>
  )
}


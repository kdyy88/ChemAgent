'use client'

import { motion, type Variants } from 'framer-motion'
import { Beaker, BrainCircuit, Network, Zap } from 'lucide-react'
import { ParticleBackground } from './ParticleBackground'

export function HomeLandingPage() {
  const containerVariants: Variants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.15,
        delayChildren: 0.2,
      },
    },
  }

  const itemVariants: Variants = {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 120, damping: 20 } },
  }

  return (
    <div className="relative w-full h-full overflow-hidden flex flex-col items-center justify-center bg-zinc-50/50 dark:bg-zinc-950/50">
      {/* Dynamic Background */}
      {/* <ParticleBackground /> */}

      {/* Main Content */}
      <div className="z-10 flex flex-col items-center max-w-4xl px-6 text-center">
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="flex flex-col items-center"
        >
          {/* Badge */}
          <motion.div variants={itemVariants} className="mb-6">
            <span className="inline-flex items-center rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary shadow-sm backdrop-blur-sm">
              <SparklesIcon className="mr-1.5 h-3.5 w-3.5" />
              v2.0 Workspace Engine
            </span>
          </motion.div>

          {/* Title */}
          <motion.h1 
            variants={itemVariants} 
            className="text-5xl md:text-6xl font-light tracking-tight text-foreground mb-6"
            style={{ fontFamily: 'Inter, sans-serif' }}
          >
            ChemAgent <span className="font-semibold text-primary">Workspace</span>
          </motion.h1>

          {/* Subtitle */}
          <motion.p 
            variants={itemVariants}
            className="text-lg md:text-xl text-muted-foreground font-light max-w-2xl mb-16 leading-relaxed"
          >
            新一代高通量计算与多智能体化学工作台。在左侧选择专业计算工具，右侧召唤 AI Copilot，开启您的分子探索之旅。
          </motion.p>

          {/* Feature Cards */}
          <motion.div 
            variants={containerVariants}
            className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full max-w-3xl"
          >
            <FeatureCard 
              icon={<Beaker className="h-5 w-5" />}
              title="12+ 专业计算工具"
              description="集成 RDKit 与 Open Babel 的结构清理、药效团分析与高通量 3D 构象优化。"
            />
            <FeatureCard 
              icon={<BrainCircuit className="h-5 w-5" />}
              title="Agentic 深度穿透"
              description="对话中的上下文与侧边栏参数完美衔接，AI 可直接接管您的分子输入与参数编排。"
            />
            <FeatureCard 
              icon={<Network className="h-5 w-5" />}
              title="SDF 高通量处理"
              description="百万级结构库的拆分、合并与力场打分，内存流式处理，零落盘损耗。"
            />
          </motion.div>
        </motion.div>
      </div>

      {/* Aesthetic gradients */}
      <div className="pointer-events-none absolute inset-0 -z-10 flex items-center justify-center">
        <div className="absolute top-1/2 left-1/2 -mt-[300px] -ml-[300px] h-[600px] w-[600px] rounded-full bg-primary/5 blur-3xl" />
        <div className="absolute top-1/2 left-1/2 mt-[100px] -ml-[400px] h-[400px] w-[400px] rounded-full bg-blue-500/5 blur-3xl" />
      </div>
    </div>
  )
}

function FeatureCard({ icon, title, description }: { icon: React.ReactNode, title: string, description: string }) {
  return (
    <motion.div 
      variants={{
        hidden: { opacity: 0, y: 20 },
        visible: { opacity: 1, y: 0 }
      }}
      whileHover={{ y: -5, scale: 1.02 }}
      className="flex flex-col items-center text-center p-6 rounded-2xl bg-background/60 backdrop-blur-md border border-border/50 shadow-xl shadow-black/5 dark:shadow-black/20"
    >
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
        {icon}
      </div>
      <h3 className="mb-2 text-base font-medium">{title}</h3>
      <p className="text-sm text-muted-foreground font-light leading-relaxed">
        {description}
      </p>
    </motion.div>
  )
}

function SparklesIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M9.937 15.5A2 2 0 008.5 14.063l-6.135-1.582a.5.5 0 010-.962L8.5 9.936A2 2 0 009.937 8.5l1.582-6.135a.5.5 0 01.963 0L14.063 8.5A2 2 0 0015.5 9.937l6.135 1.581a.5.5 0 010 .964L15.5 14.063a2 2 0 00-1.437 1.437l-1.582 6.135a.5.5 0 01-.963 0z" />
    </svg>
  )
}

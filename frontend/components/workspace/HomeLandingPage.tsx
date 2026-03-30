'use client'

import { motion, type Variants } from 'framer-motion'
import { Beaker, BrainCircuit, Network } from 'lucide-react'

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
    <div className="relative w-full h-full overflow-hidden flex flex-col items-center justify-center bg-background/50">
      {/* Radial teal glow — background atmosphere */}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-[500px] w-[500px] rounded-full bg-primary/8 blur-[80px]" />
        <div className="absolute top-1/4 right-1/4 h-[250px] w-[250px] rounded-full bg-primary/5 blur-[60px]" />
      </div>

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
            {/* Decorative molecular hex ring */}
            <svg
              className="mx-auto mb-4 w-16 h-16 text-primary/30"
              viewBox="0 0 64 64"
              fill="none"
              stroke="currentColor"
              strokeWidth="1"
              aria-hidden="true"
            >
              <polygon points="32,4 58,18 58,46 32,60 6,46 6,18" strokeLinejoin="round" />
              <polygon points="32,14 50,24 50,44 32,54 14,44 14,24" strokeLinejoin="round" opacity="0.5" />
              <circle cx="32" cy="32" r="5" fill="currentColor" opacity="0.4" />
              {[0,1,2,3,4,5].map(i => {
                const angle = (i * 60 - 90) * Math.PI / 180
                const x = 32 + 19 * Math.cos(angle)
                const y = 32 + 19 * Math.sin(angle)
                return <circle key={i} cx={x} cy={y} r="2.5" fill="currentColor" opacity="0.5" />
              })}
            </svg>
            <span className="inline-flex items-center rounded-full border border-primary/25 bg-primary/10 px-3 py-1 text-xs font-semibold text-primary tracking-wide shadow-sm shadow-primary/10 backdrop-blur-sm">
              <SparklesIcon className="mr-1.5 h-3.5 w-3.5" />
              v2.0 · Molecular Workspace Engine
            </span>
          </motion.div>

          {/* Title */}
          <motion.h1
            variants={itemVariants}
            className="font-display text-5xl md:text-6xl font-bold tracking-tight mb-6 text-balance"
          >
            <span className="bg-gradient-to-r from-foreground via-foreground to-foreground/60 bg-clip-text text-transparent">
              Chem
            </span>
            <span className="bg-gradient-to-r from-primary via-primary to-primary/70 bg-clip-text text-transparent">
              Agent
            </span>{" "}
            <span className="bg-gradient-to-br from-foreground/80 to-foreground/40 bg-clip-text text-transparent font-light">
              Workspace
            </span>
          </motion.h1>

          {/* Subtitle */}
          <motion.p
            variants={itemVariants}
            className="text-base md:text-lg text-muted-foreground font-light max-w-xl mb-12 leading-relaxed text-pretty"
          >
            权威检索 · 结构化工具调用 · 可解释流式过程展示
            <br />
            <span className="text-xs tracking-widest font-mono text-muted-foreground/60 uppercase mt-1 block">
              Authoritative · Structured · Explainable
            </span>
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
      whileHover={{ y: -4 }}
      className="group relative flex flex-col p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border hover:border-primary/40 shadow-sm hover:shadow-primary/10 hover:shadow-lg transition-all duration-300 overflow-hidden text-left"
    >
      {/* Teal left-border accent */}
      <div className="absolute left-0 top-4 bottom-4 w-[2px] rounded-r bg-primary/40 group-hover:bg-primary transition-colors duration-300" />

      <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary group-hover:bg-primary/15 transition-colors duration-300 ml-2">
        {icon}
      </div>
      <h3 className="mb-1.5 text-sm font-semibold ml-2">{title}</h3>
      <p className="text-xs text-muted-foreground leading-relaxed ml-2">
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

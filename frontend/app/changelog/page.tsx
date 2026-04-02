'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { FlaskConical, ArrowLeft, Calendar, Tag } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ThemeToggle } from '@/components/ui/ThemeToggle'
import { LanguageSwitcher } from '@/components/ui/LanguageSwitcher'
import { cn } from '@/lib/utils'

// ─── Data ────────────────────────────────────────────────────────────────────

type ChangeType = 'Feature' | 'Fix' | 'Refactor' | 'Improvement' | 'Style' | 'Removed'

interface ChangeEntry {
  type: ChangeType
  content: string
}

interface ChangelogVersion {
  version: string
  date: string
  highlight?: string
  sections: ChangeEntry[]
}

const CHANGELOG: ChangelogVersion[] = [
  {
    version: 'v1.3.0',
    date: '2026-04-03',
    highlight: '双层引擎架构 & 3D 分子可视化',
    sections: [
      { type: 'Feature', content: '双层生成器引擎架构 (ChemSessionEngine)：外层负责生命周期与拦截器，内层封装 LangGraph astream_events(v2)，实现控制面/数据面隔离' },
      { type: 'Feature', content: 'Artifact Pointer 拦截器：sdf_content / pdbqt_content 等大字段自动剥离至 Redis 数据面，前端仅接收轻量级 art_* ID 指针' },
      { type: 'Feature', content: 'Error Withholding 错误扣留：valence / invalid SMILES / kekulize 等可自愈化学错误自动注入修正提示并重试（最多 3 次），不暴露给用户' },
      { type: 'Feature', content: 'GET /api/chat/artifacts/{id} 端点：Redis TTL 1 小时，支持跨请求 artifact 取用，Redis 不可用时自动降级至进程内 FIFO 缓存（256 条上限）' },
      { type: 'Feature', content: '全局双模切换 (Copilot / Agent)：uiStore 持久化模式偏好，刷新后保持；Agent 模式暂未开放，置灰显示' },
      { type: 'Feature', content: 'Agent 模式全屏沉浸式布局：左侧 30% 对话面板 + 右侧 70% Artifact 画布，原生 pointer events 实现可拖拽分割线' },
      { type: 'Feature', content: 'ArtifactCanvas：从 SSE turns 中实时收集 artifact 事件，masonry 瀑布流布局展示 MoleculeImageRenderer / SdfRenderer / PdbqtRenderer 等卡片' },
      { type: 'Feature', content: '3D 交互式分子可视化 (3Dmol.js WebGL)：支持 SDF / PDBQT 格式，球棍模型 + rasmol 配色，next/dynamic 懒加载不影响首屏' },
      { type: 'Feature', content: 'Mol3DViewerGuard：IntersectionObserver + 条件卸载（非 clear()），视口外分子卡片真正释放 GPU 显存，支持 20+ 卡片并发不崩溃' },
      { type: 'Feature', content: '分子卡片放大预览弹窗 (1024×768px)：弹窗打开时自动挂起小窗 WebGL context，关闭后重新初始化，始终只持有 1 个活跃 context' },
      { type: 'Feature', content: 'SDF 格式自愈 (normalizeSdf)：自动修复因 .trim() 导致 V2000 header 行偏移问题，防御性处理后端传来的所有 SDF' },
      { type: 'Refactor', content: 'sse_chat.py 从 748 行精简至 ~110 行，路由层只剩请求模型与 StreamingResponse，全部业务逻辑下沉至 ChemSessionEngine' },
      { type: 'Improvement', content: 'Agent 模式下聊天气泡不再渲染 Artifact（SDF/图片/Lipinski），全部路由至右侧 ArtifactCanvas，彻底解耦控制流与数据展示' },
      { type: 'Improvement', content: 'ModeToggle 从全局 Header 收归至 CopilotSidebar 标题栏，排版更紧凑；Copilot/Agent 模式切换保留 framer-motion 弹簧滑块动画' },
      { type: 'Improvement', content: 'React.memo 自定义比较器封锁 Molecule3DViewer，SSE 流式输出期间的高频 re-render 不再触发 WebGL 重建' },
      { type: 'Improvement', content: '3Dmol antialias: false + quality: "low"：禁用 MSAA 并降低几何体精度，多卡片场景帧率显著提升，集成显卡友好' },
      { type: 'Fix', content: 'SDF atom count: 0 根治：V2000 Counts Line 必须在第 4 行，normalizeSdf 自动检测偏移并补齐空行' },
      { type: 'Fix', content: '3Dmol backgroundColor 不接受 oklch/lab CSS 函数，改为检测 dark class 直接返回安全 hex 值' },
      { type: 'Fix', content: '_local_fallback dict 无上限增长问题修复：改用 FIFO 队列，Redis 降级期间最多缓存 256 条 artifact' },
    ],
  },
  {
    version: 'v1.2.0',
    date: '2026-04-01',
    highlight: '全栈国际化 & UI 焕新',
    sections: [
      { type: 'Feature', content: '完整的双语 (zh/en) i18n 架构，基于 Next.js 15 App Router 中间件实现路由级语言切换（/zh/ · /en/）' },
      { type: 'Feature', content: '右上角语言下拉切换器，首次访问自动识别浏览器语言偏好' },
      { type: 'Feature', content: 'SSE 事件实时翻译拦截器：LangGraph 推回的节点名、工具标签、状态描述全部动态本地化' },
      { type: 'Feature', content: '独立 chemistry 命名空间，RDKit / Open Babel 术语表与通用 UI 文案分离' },
      { type: 'Feature', content: 'Zustand i18n Store 持久化语言偏好，刷新后不丢失' },
      { type: 'Feature', content: 'ResearchThinking 思考面板完整汉英双语适配（标题、阶段计数、badge、进行中等）' },
      { type: 'Improvement', content: '首次连接失败时错误提示改为可读消息，修复命名空间未加载时显示原始 key 的竞态问题' },
      { type: 'Style', content: '数据源下拉菜单全面重设计：圆角 icon badge、backdrop-blur 容器、分隔线、pill 标签符合整体风格' },
      { type: 'Removed', content: '废弃的 Workflow Editor 页面及相关 orchestrator 组件已从项目中完全移除' },
      { type: 'Fix', content: 'ToolSidebar：修复 `// eslint-disable` 行注释错误渲染为可见文字的问题' },
      { type: 'Fix', content: '发送按钮由 type="submit" 改为 type="button" + onClick，修复 PromptInput（div 容器）内无 form 时无法触发的 bug' },
    ],
  },
  {
    version: 'v1.1.0',
    date: '2026-03-15',
    highlight: 'Agentic 流式推理展示',
    sections: [
      { type: 'Feature', content: '新增 ResearchThinking 组件，实时展示 LangGraph 各节点推理过程与工具调用步骤' },
      { type: 'Feature', content: 'SSE 流式连接支持 fetch-event-source，处理 on_tool_start / on_chain_end 等完整事件类型' },
      { type: 'Feature', content: 'ClarificationCard：Agent 需要用户澄清时展示结构化表单，支持快速回复按钮' },
      { type: 'Feature', content: 'TaskTracker：多任务并行时展示可折叠任务清单，含实时进度标记' },
      { type: 'Improvement', content: 'CopilotSidebar 新增对话轮次计数与一键清除历史' },
      { type: 'Fix', content: '修复长 SMILES 字符串在标签显示时未截断的问题' },
    ],
  },
  {
    version: 'v1.0.0',
    date: '2026-03-01',
    highlight: '首次公开发布',
    sections: [
      { type: 'Feature', content: '三栏可拖拽布局：工具侧边栏 · 分子工作区 · AI 对话面板' },
      { type: 'Feature', content: '集成 12+ RDKit 与 Open Babel 专业化工工具（SMILES 验证、脱盐、分子描述符、相似性、子结构搜索等）' },
      { type: 'Feature', content: '3D 分子查看器，支持 SDF / SMILES 渲染与 SMILES 复制' },
      { type: 'Feature', content: 'SDF 批量处理：百万级结构库的拆分、合并与力场打分，内存流式处理' },
      { type: 'Feature', content: '深色 / 浅色主题切换，科研冷白实验室配色方案' },
      { type: 'Feature', content: '移动端响应式布局，小屏幕自动切换为竖向可拖拽面板' },
    ],
  },
]

// ─── Badge styling ────────────────────────────────────────────────────────────

const BADGE_STYLES: Record<ChangeType, string> = {
  Feature:     'bg-primary/10 text-primary border-primary/25 hover:bg-primary/15',
  Fix:         'bg-amber-500/10 text-amber-600 border-amber-500/25 dark:text-amber-400',
  Refactor:    'bg-purple-500/10 text-purple-600 border-purple-500/25 dark:text-purple-400',
  Improvement: 'bg-sky-500/10 text-sky-600 border-sky-500/25 dark:text-sky-400',
  Style:       'bg-emerald-500/10 text-emerald-600 border-emerald-500/25 dark:text-emerald-400',
  Removed:     'bg-red-500/10 text-red-600 border-red-500/25 dark:text-red-400',
}

const BADGE_LABELS: Record<ChangeType, string> = {
  Feature:     '新功能',
  Fix:         '修复',
  Refactor:    '重构',
  Improvement: '优化',
  Style:       '样式',
  Removed:     '移除',
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function ChangelogPage() {
  const [activeVersion, setActiveVersion] = useState(CHANGELOG[0].version)
  const sectionRefs = useRef<Map<string, HTMLElement>>(new Map())

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible.length > 0) {
          setActiveVersion(visible[0].target.id.replace('version-', ''))
        }
      },
      { rootMargin: '-10% 0px -70% 0px', threshold: 0 },
    )
    sectionRefs.current.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [])

  const scrollTo = (version: string) => {
    const el = sectionRefs.current.get(version)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="flex flex-col min-h-[100dvh] bg-background">
      {/* ── Navbar ──────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 shrink-0 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto max-w-5xl px-4 md:px-6 py-3 flex items-center gap-2.5">
          <Link
            href="/"
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary ring-2 ring-primary/20 shrink-0"
            aria-label="回首页"
          >
            <FlaskConical className="h-4 w-4 text-primary-foreground" />
          </Link>
          <div className="flex-1">
            <h1 className="font-display text-sm font-bold leading-none tracking-wide">
              Chem<span className="text-primary">Agent</span>
            </h1>
            <p className="text-[10px] text-muted-foreground mt-0.5 font-mono tracking-widest uppercase">
              Changelog
            </p>
          </div>
          <Link
            href="/"
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mr-1"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">返回应用</span>
          </Link>
          <LanguageSwitcher />
          <ThemeToggle />
        </div>
      </header>

      {/* ── Mobile version strip ─────────────────────────────────────── */}
      <div className="md:hidden sticky top-[57px] z-20 border-b bg-background/95 backdrop-blur overflow-x-auto scrollbar-thin">
        <div className="flex items-center gap-1.5 px-4 py-2 w-max">
          {CHANGELOG.map(({ version }) => (
            <button
              key={version}
              onClick={() => scrollTo(version)}
              className={cn(
                'shrink-0 rounded-full px-3 py-1 text-xs font-mono font-medium transition-colors',
                activeVersion === version
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground',
              )}
            >
              {version}
            </button>
          ))}
        </div>
      </div>

      {/* ── Main ────────────────────────────────────────────────────── */}
      <main className="flex-1">
        <div className="mx-auto max-w-5xl px-4 md:px-6 py-10 md:py-16">
          {/* Page heading */}
          <div className="mb-10 md:mb-14">
            <div className="flex items-center gap-2 text-primary mb-2">
              <Tag className="h-4 w-4" />
              <span className="text-xs font-semibold uppercase tracking-widest font-mono">Changelog</span>
            </div>
            <h2 className="font-display text-3xl md:text-4xl font-bold tracking-tight">更新日志</h2>
            <p className="mt-2 text-sm text-muted-foreground max-w-xl">
              ChemAgent 每个版本的功能新增、问题修复与架构优化记录。
            </p>
          </div>

          <div className="flex gap-10 md:gap-14">
            {/* ── Left sidebar ──────────────────────────────────────── */}
            <aside className="hidden md:flex flex-col gap-0 w-44 shrink-0">
              <div className="sticky top-[73px]">
                <p className="mb-4 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
                  版本列表
                </p>
                <div className="relative pl-4">
                  <div className="absolute left-1.5 top-1 bottom-1 w-px bg-border/60" />
                  <div className="flex flex-col gap-0.5">
                    {CHANGELOG.map(({ version, highlight }) => {
                      const isActive = activeVersion === version
                      return (
                        <button
                          key={version}
                          onClick={() => scrollTo(version)}
                          className={cn(
                            'group relative text-left rounded-lg px-2.5 py-2 transition-all duration-150',
                            isActive
                              ? 'bg-primary/8 text-foreground'
                              : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
                          )}
                        >
                          <span
                            className={cn(
                              'absolute -left-[11px] top-1/2 -translate-y-1/2 h-2 w-2 rounded-full border-2 transition-all duration-150',
                              isActive
                                ? 'bg-primary border-primary scale-110'
                                : 'bg-background border-border group-hover:border-primary/50',
                            )}
                          />
                          <span className={cn('block text-xs font-mono font-semibold', isActive && 'text-primary')}>
                            {version}
                          </span>
                          {highlight && (
                            <span className="block text-[10px] leading-snug mt-0.5 text-muted-foreground/70 truncate">
                              {highlight}
                            </span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
            </aside>

            {/* ── Right content ─────────────────────────────────────── */}
            <div className="flex-1 min-w-0 flex flex-col gap-14">
              {CHANGELOG.map(({ version, date, sections }, idx) => (
                <section
                  key={version}
                  id={`version-${version}`}
                  ref={(el) => {
                    if (el) sectionRefs.current.set(version, el)
                    else sectionRefs.current.delete(version)
                  }}
                  className="scroll-mt-24"
                >
                  <div className="flex flex-wrap items-baseline gap-3 mb-6">
                    <h3 className="font-display font-bold text-2xl md:text-3xl tracking-tight">{version}</h3>
                    <div className="flex items-center gap-1.5 text-muted-foreground text-xs">
                      <Calendar className="h-3.5 w-3.5" />
                      <time dateTime={date}>{date}</time>
                    </div>
                  </div>

                  <div className="flex flex-col gap-2.5">
                    {sections.map((entry, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-3 rounded-xl border border-border/50 bg-card/60 px-4 py-3.5 hover:border-border hover:bg-card transition-colors"
                      >
                        <Badge
                          variant="outline"
                          className={cn(
                            'shrink-0 mt-0.5 text-[10px] font-semibold leading-none px-1.5 py-0.5 rounded-md',
                            BADGE_STYLES[entry.type],
                          )}
                        >
                          {BADGE_LABELS[entry.type]}
                        </Badge>
                        <p className="text-sm text-foreground/85 leading-relaxed">{entry.content}</p>
                      </div>
                    ))}
                  </div>

                  {idx < CHANGELOG.length - 1 && (
                    <Separator className="mt-14 bg-border/40" />
                  )}
                </section>
              ))}
            </div>
          </div>
        </div>
      </main>

      <footer className="shrink-0 border-t bg-background/95 pt-1 pb-1">
        <p className="text-center text-[10px] text-muted-foreground/70 select-none">
          © {new Date().getFullYear()} ChemAgent · Designed &amp; developed by Yuan Ye · Consulting by Kelly
        </p>
      </footer>
    </div>
  )
}

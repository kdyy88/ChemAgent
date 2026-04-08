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
    version: 'v1.4.0',
    date: '2026-04-03',
    highlight: '操作审批 & 长对话稳定性',
    sections: [
      { type: 'Feature', content: '高风险操作审批弹窗：AI 在执行某些耗时或不可逆的操作前会暂停并向你展示一张确认卡片，你可以选择"拒绝"、"直接执行"或"修改参数后执行"，全程掌控' },
      { type: 'Feature', content: '审批等待时输入框自动锁定：AI 等待你确认期间，聊天输入框会变灰并提示"等待你的确认"，避免新消息打断流程' },
      { type: 'Feature', content: '长对话不再报错：当对话轮次很多时，系统会自动压缩早期工具调用内容，保留最近 5 次完整结果，其余替换为简短占位，防止超出 AI 上下文限制' },
      { type: 'Feature', content: '超长工具结果自动截断：单次工具返回内容过长时（如超大 SMILES 列表），自动保留开头和结尾各 2000 字符并标注省略了多少内容，而不是整段丢弃' },
      { type: 'Improvement', content: 'AI 每次回复后在后台记录本轮消耗的 token 数量，上下文接近上限时会自动写入告警日志，便于开发者排查' },
      { type: 'Fix', content: '修复"找不到工具输出"报错：当用户在 AI 调用工具期间中断对话，再次发送消息时会触发 400 错误；现在系统会自动补全中断的工具调用记录，恢复正常' },
      { type: 'Fix', content: '修复 AI 同时调用多个工具时报错的问题：AI 并行执行多个分析任务（如同时生成 5 个分子）时，系统曾错误地将多条结果合并，导致 400 报错；现已修复，每条结果独立保留' },
      { type: 'Refactor', content: '升级至 Next.js 16 路由规范，用户无感知，内部路由配置文件随版本要求同步更新' },
    ],
  },
  {
    version: 'v1.3.0',
    date: '2026-04-03',
    highlight: '双模式布局 & 3D 分子查看器',
    sections: [
      { type: 'Feature', content: '全新 Agent 模式布局：左侧 30% 为对话区，右侧 70% 为分子展示画布，两侧分割线可自由拖动调节宽度，专为长时间分子设计任务优化' },
      { type: 'Feature', content: '3D 交互式分子查看器：AI 生成的分子结构可以在浏览器里直接旋转、缩放、查看立体构型，基于 WebGL 渲染，支持 SDF 和 PDBQT 两种格式' },
      { type: 'Feature', content: '分子卡片点击放大预览：点击任意分子卡片可弹出 1024×768 的大窗口，放大查看 3D 结构细节，关闭后自动恢复列表视图' },
      { type: 'Feature', content: 'Copilot / Agent 双模式全局切换：右上角可一键切换两种交互模式，偏好刷新后自动保留；Agent 模式后续开放，目前显示为置灰状态' },
      { type: 'Feature', content: '大文件自动卸载：当分子卡片滚动到屏幕外时，3D 渲染资源会自动释放，页面同时展示 20 张以上分子卡片也不会卡顿或崩溃' },
      { type: 'Improvement', content: 'AI 返回的化学错误（如无效 SMILES）不再直接暴露给用户，系统会自动重试修正（最多 3 次），只有真正无法恢复时才提示错误' },
      { type: 'Improvement', content: 'Agent 模式下分子图片、3D 结构、理化性质等结果统一展示在右侧画布，不再混在聊天气泡里，阅读更清晰' },
      { type: 'Improvement', content: '3D 渲染针对集成显卡优化：关闭抗锯齿并降低几何精度，多卡片场景下帧率明显提升，低配置设备也能流畅使用' },
      { type: 'Fix', content: '修复分子 3D 展示黑色背景问题：深色模式下背景颜色与主题保持一致，不再出现黑块' },
      { type: 'Fix', content: '修复 SDF 文件原子数显示为 0 的问题：自动检测文件格式偏移并补齐标准头部结构' },
      { type: 'Refactor', content: '后端核心代码大幅精简重构，对话响应逻辑与引擎逻辑分离，用户无感知但系统更加稳定，后续功能扩展更容易' },
    ],
  },
  {
    version: 'v1.2.0',
    date: '2026-04-01',
    highlight: '中英双语支持 & 界面焕新',
    sections: [
      { type: 'Feature', content: '完整的中文 / 英文双语支持：右上角可随时切换语言，首次访问自动根据浏览器语言选择，刷新后记住你的偏好' },
      { type: 'Feature', content: 'AI 推理过程实时本地化：AI 执行每一步工具调用时显示的节点名称、状态描述也随语言切换同步翻译' },
      { type: 'Improvement', content: '连接失败时的错误提示改为更易读的中文描述，不再显示原始错误代码' },
      { type: 'Style', content: '数据源选择下拉菜单全面重新设计：圆角图标徽章、磨砂玻璃背景、分割线与标签样式，整体视觉风格更统一' },
      { type: 'Removed', content: '移除了废弃的 Workflow Editor 页面，应用结构更简洁' },
      { type: 'Fix', content: '修复代码注释被错误渲染为可见文字的显示 Bug' },
      { type: 'Fix', content: '修复发送按钮在某些情况下点击无反应的问题' },
    ],
  },
  {
    version: 'v1.1.0',
    date: '2026-03-15',
    highlight: 'AI 思考过程可视化',
    sections: [
      { type: 'Feature', content: 'AI 推理过程实时展示：AI 回答时可以看到它正在调用哪些工具、执行哪些步骤，不再是黑盒等待' },
      { type: 'Feature', content: '澄清卡片：当你的问题需要补充信息时，AI 会弹出结构化的澄清表单，提供快速回复选项，无需手动打字' },
      { type: 'Feature', content: '多任务进度追踪器：AI 同时处理多个子任务时，会显示可折叠的任务清单并实时标记完成状态' },
      { type: 'Improvement', content: '对话面板新增轮次计数与一键清除历史记录按钮' },
      { type: 'Fix', content: '修复过长的 SMILES 字符串在标签中不截断导致布局溢出的问题' },
    ],
  },
  {
    version: 'v1.0.0',
    date: '2026-03-01',
    highlight: '首次公开发布',
    sections: [
      { type: 'Feature', content: '三栏可拖拽主界面：左侧工具箱、中央分子工作区、右侧 AI 对话面板，三栏宽度均可自由拖动调节' },
      { type: 'Feature', content: '12 种以上专业化学工具：涵盖 SMILES 合法性验证、分子脱盐、理化性质计算、结构相似性搜索、子结构匹配等常用操作' },
      { type: 'Feature', content: '3D 分子查看器：支持直接输入 SMILES 或上传 SDF 文件查看立体结构，并可一键复制 SMILES' },
      { type: 'Feature', content: 'SDF 批量处理：支持对大型化合物库进行拆分、合并与力场评分，采用流式处理，百万级结构不卡顿' },
      { type: 'Feature', content: '深色 / 浅色主题切换，科研冷白实验室配色方案' },
      { type: 'Feature', content: '移动端适配：小屏幕设备自动切换为竖向布局，手机也可正常使用' },
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

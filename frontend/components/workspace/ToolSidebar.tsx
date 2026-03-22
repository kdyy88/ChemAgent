'use client'

import { useState } from 'react'
import {
  FlaskConical,
  LayoutDashboard,
  Box,
  Sparkles,
  SlidersHorizontal,
  ChevronDown,
  ChevronRight,
  Search,
  Beaker,
  Atom,
  Layers,
  ArrowLeftRight,
  FileCheck,
  Droplets,
  Home,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useWorkspaceStore, type NavMode, type FunctionId } from '@/store/workspaceStore'

const SOFTWARE_TREE = [
  {
    title: 'RDKit (Python)',
    icon: <FlaskConical className="w-3.5 h-3.5" />,
    items: [
      { id: 'validate',     label: 'SMILES 验证' },
      { id: 'salt-strip',   label: '脱盐与中和' },
      { id: 'descriptors',  label: '综合分子描述符' },
      { id: 'similarity',   label: '分子相似性' },
      { id: 'substructure', label: '子结构搜索 / PAINS' },
      { id: 'scaffold',     label: 'Murcko 骨架' },
    ]
  },
  {
    title: 'Open Babel',
    icon: <Box className="w-3.5 h-3.5" />,
    items: [
      { id: 'mol-properties', label: '分子物理属性' },
      { id: 'partial-charge', label: '原子偏电荷分析' },
      { id: 'convert',        label: '分子格式转换' },
      { id: 'conformer',      label: '3D 构象生成' },
      { id: 'pdbqt',          label: '对接预处理 (PDBQT)' },
      { id: 'sdf-batch',      label: 'SDF 批量处理' },
    ]
  }
]

const BUSINESS_TREE = [
  {
    title: '数据清洗与准备',
    icon: <Droplets className="w-3.5 h-3.5" />,
    items: [
      { id: 'validate',   label: 'SMILES 规范化与查错' },
      { id: 'salt-strip',   label: '脱盐与分子中和' },
    ]
  },
  {
    title: '物理化学性质',
    icon: <Beaker className="w-3.5 h-3.5" />,
    items: [
      { id: 'descriptors',    label: '综合描述符 (含 Lipinski / QED / SA)' },
      { id: 'mol-properties', label: '核心物理属性 (精确质量等)' },
    ]
  },
  {
    title: '结构分析与检索',
    icon: <Search className="w-3.5 h-3.5" />,
    items: [
      { id: 'similarity',   label: '相似度比对 (Tanimoto)' },
      { id: 'substructure', label: '药效团与毒性警示 (PAINS)' },
      { id: 'scaffold',     label: '核心骨架提取 (Murcko)' },
      { id: 'partial-charge', label: '原子偏电荷分析' },
    ]
  },
  {
    title: '3D 与对接处理',
    icon: <SlidersHorizontal className="w-3.5 h-3.5" />,
    items: [
      { id: 'convert',   label: '格式转换' },
      { id: 'conformer', label: '3D 构象生成' },
      { id: 'pdbqt',     label: 'PDBQT 预处理' },
      { id: 'sdf-batch', label: 'SDF 库批量处理' },
    ]
  }
]

export function ToolSidebar() {
  const { navMode, setNavMode, activeFunctionId, setActiveFunctionId } = useWorkspaceStore()
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    'RDKit (Python)': true,
    'Open Babel': true,
    '数据清洗与准备': true,
    '物理化学性质': true,
    '结构分析与检索': true,
    '3D 与对接处理': true,
  })

  const toggleSection = (title: string) => {
    setExpandedSections(prev => ({ ...prev, [title]: !prev[title] }))
  }

  const tree = navMode === 'software' ? SOFTWARE_TREE : BUSINESS_TREE

  return (
    <div className="flex h-full bg-background border-r">
      {/* Activity Bar */}
      <div className="w-[50px] shrink-0 border-r bg-muted/30 flex flex-col items-center py-4 gap-4">
        <button 
          onClick={() => setNavMode('software')}
          className={`p-2.5 rounded-lg transition-colors ${navMode === 'software' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
          title="按软件组件视角"
        >
          <Box className="w-5 h-5" />
        </button>
        <button 
          onClick={() => setNavMode('business')}
          className={`p-2.5 rounded-lg transition-colors ${navMode === 'business' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
          title="按业务场景视角"
        >
          <LayoutDashboard className="w-5 h-5" />
        </button>
      </div>

      {/* Primary Sidebar */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-4 py-3 border-b shrink-0 flex items-center justify-between h-[49px]">
          <h2 className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
            {navMode === 'software' ? '软件组件库' : '业务场景流'}
          </h2>
          <button 
            onClick={() => setActiveFunctionId(null)}
            className="p-1.5 hover:bg-muted/80 rounded-md text-muted-foreground hover:text-foreground transition-colors"
            title="回首页"
          >
            <Home className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 scrollbar-thin overflow-x-hidden">
          <AnimatePresence mode="wait">
            <motion.div
              key={navMode}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              transition={{ duration: 0.15, ease: "easeInOut" }}
            >
              {tree.map(section => {
                const isExpanded = expandedSections[section.title]
                return (
                  <div key={section.title} className="mb-2">
                    <button 
                      onClick={() => toggleSection(section.title)}
                      className="flex items-center w-full px-1.5 py-1.5 text-sm font-medium text-foreground hover:bg-muted/50 rounded-md transition-colors"
                    >
                      <span className="mr-1 text-muted-foreground">
                        {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      </span>
                      <span className="mr-1.5 text-muted-foreground">{section.icon}</span>
                      <span className="truncate flex-1 text-left">{section.title}</span>
                    </button>
                    {/* Collapsible content animation */}
                    <AnimatePresence initial={false}>
                      {isExpanded && (
                        <motion.div 
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          className="mt-1 overflow-hidden"
                        >
                          {section.items.map(item => (
                            <button
                              key={item.id}
                              onClick={() => setActiveFunctionId(item.id as FunctionId)}
                              className={`flex items-center w-full pl-6 pr-2 py-1.5 text-xs rounded-md transition-colors ${activeFunctionId === item.id ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground hover:bg-muted text-foreground'}`}
                            >
                              <span className="truncate flex-1 text-left">{item.label}</span>
                            </button>
                          ))}
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )
              })}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}

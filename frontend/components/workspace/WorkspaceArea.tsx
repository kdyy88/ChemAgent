'use client'

import { FlaskConical } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useWorkspaceStore } from '@/store/workspaceStore'

// ── New Tools ────────────────────────────────────────────────────────────────
import { ValidateTool } from './tools/ValidateTool'
import { SaltStripTool } from './tools/SaltStripTool'
import { DescriptorsTool } from './tools/DescriptorsTool'
import { SimilarityTool } from './tools/SimilarityTool'
import { SubstructureTool } from './tools/SubstructureTool'
import { ScaffoldTool } from './tools/ScaffoldTool'
import { MolPropertyTool } from './tools/MolPropertyTool'
import { PartialChargeTool } from './tools/PartialChargeTool'
import { SdfBatchTool } from './tools/SdfBatchTool'
import { HomeLandingPage } from './HomeLandingPage'

// ── Existing Tools ───────────────────────────────────────────────────────────
import { ConvertTool } from './tools/ConvertTool'
import { ConformerTool } from './tools/ConformerTool'
import { PdbqtTool } from './tools/PdbqtTool'

const TOOL_TITLES: Record<string, string> = {
  'validate':       'SMILES 验证与规范化',
  'salt-strip':     '脱盐与分子中和',
  'descriptors':    '综合分子描述符',
  'mol-properties': '核心物理属性',
  'partial-charge': '原子偏电荷分析',
  'similarity':     '分子相似性比对',
  'substructure':   '子结构搜索 + PAINS',
  'scaffold':       'Murcko 骨架提取',
  'convert':        '分子格式转换',
  'conformer':      '3D 构象生成',
  'pdbqt':          '对接预处理 (PDBQT)',
  'sdf-batch':      'SDF 库批量处理',
}

export function WorkspaceArea() {
  const { activeFunctionId } = useWorkspaceStore()

  if (!activeFunctionId) {
    return <HomeLandingPage />
  }

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden p-6 sm:p-8 md:p-10 lg:p-12 gap-0">
      <div className="shrink-0 pb-6 mb-6 border-b">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <FlaskConical className="h-6 w-6 text-primary" />
          {TOOL_TITLES[activeFunctionId] || '化学主工作台'}
        </h2>
        <p className="text-sm text-muted-foreground mt-2">
          核心流程操作区 · 左侧选择任务功能
        </p>
      </div>

      <div className="flex-1 flex flex-col gap-4 min-h-0 pb-8 overflow-y-auto p-2 scrollbar-thin max-w-4xl overflow-x-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeFunctionId}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="flex flex-col gap-4"
          >
            {activeFunctionId === 'validate'       && <ValidateTool />}
            {activeFunctionId === 'salt-strip'     && <SaltStripTool />}
            {activeFunctionId === 'descriptors'    && <DescriptorsTool />}
            {activeFunctionId === 'mol-properties' && <MolPropertyTool />}
            {activeFunctionId === 'partial-charge' && <PartialChargeTool />}
            {activeFunctionId === 'similarity'     && <SimilarityTool />}
            {activeFunctionId === 'substructure'   && <SubstructureTool />}
            {activeFunctionId === 'scaffold'       && <ScaffoldTool />}
            {activeFunctionId === 'convert'        && <ConvertTool />}
            {activeFunctionId === 'conformer'      && <ConformerTool />}
            {activeFunctionId === 'pdbqt'          && <PdbqtTool />}
            {activeFunctionId === 'sdf-batch'      && <SdfBatchTool />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}

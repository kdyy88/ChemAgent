'use client'

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  FlaskConical,
  LayoutDashboard,
  Box,
  SlidersHorizontal,
  ChevronDown,
  ChevronRight,
  Search,
  Beaker,
  Droplets,
  Home,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useWorkspaceStore, type NavMode, type FunctionId } from '@/store/workspaceStore'
import { useUIStore } from '@/store/uiStore'
import '@/lib/i18n/client'

// Trees use translation keys instead of hardcoded labels
const SOFTWARE_TREE = [
  {
    titleKey: 'tool_category.rdkit',
    icon: <FlaskConical className="w-3.5 h-3.5" />,
    items: [
      { id: 'validate',     labelKey: 'tool_label.validate' },
      { id: 'salt-strip',   labelKey: 'tool_label.salt_strip' },
      { id: 'descriptors',  labelKey: 'tool_label.descriptors' },
      { id: 'similarity',   labelKey: 'tool_label.similarity' },
      { id: 'substructure', labelKey: 'tool_label.substructure' },
      { id: 'scaffold',     labelKey: 'tool_label.scaffold' },
    ]
  },
  {
    titleKey: 'tool_category.openbabel',
    icon: <Box className="w-3.5 h-3.5" />,
    items: [
      { id: 'mol-properties', labelKey: 'tool_label.mol_properties' },
      { id: 'partial-charge', labelKey: 'tool_label.partial_charge' },
      { id: 'convert',        labelKey: 'tool_label.convert' },
      { id: 'conformer',      labelKey: 'tool_label.conformer' },
      { id: 'pdbqt',          labelKey: 'tool_label.pdbqt' },
      { id: 'sdf-batch',      labelKey: 'tool_label.sdf_batch' },
    ]
  }
]

const BUSINESS_TREE = [
  {
    titleKey: 'tool_category.data_cleaning',
    icon: <Droplets className="w-3.5 h-3.5" />,
    items: [
      { id: 'validate',   labelKey: 'tool_label.validate_biz' },
      { id: 'salt-strip', labelKey: 'tool_label.salt_strip_biz' },
    ]
  },
  {
    titleKey: 'tool_category.physical_chem',
    icon: <Beaker className="w-3.5 h-3.5" />,
    items: [
      { id: 'descriptors',    labelKey: 'tool_label.descriptors_biz' },
      { id: 'mol-properties', labelKey: 'tool_label.mol_properties_biz' },
    ]
  },
  {
    titleKey: 'tool_category.structural_analysis',
    icon: <Search className="w-3.5 h-3.5" />,
    items: [
      { id: 'similarity',     labelKey: 'tool_label.similarity_biz' },
      { id: 'substructure',   labelKey: 'tool_label.substructure_biz' },
      { id: 'scaffold',       labelKey: 'tool_label.scaffold_biz' },
      { id: 'partial-charge', labelKey: 'tool_label.partial_charge_biz' },
    ]
  },
  {
    titleKey: 'tool_category.docking_3d',
    icon: <SlidersHorizontal className="w-3.5 h-3.5" />,
    items: [
      { id: 'convert',   labelKey: 'tool_label.convert_biz' },
      { id: 'conformer', labelKey: 'tool_label.conformer_biz' },
      { id: 'pdbqt',     labelKey: 'tool_label.pdbqt_biz' },
      { id: 'sdf-batch', labelKey: 'tool_label.sdf_batch_biz' },
    ]
  }
]

export function ToolSidebar() {
  const { t } = useTranslation('common')
  const { navMode, setNavMode, activeFunctionId, setActiveFunctionId } = useWorkspaceStore()
  const { isSidebarExpanded, toggleSidebar } = useUIStore()

  const initialExpanded = Object.fromEntries(
    [...SOFTWARE_TREE, ...BUSINESS_TREE].map((s) => [s.titleKey, true])
  )
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>(initialExpanded)

  const toggleSection = (key: string) => {
    setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const tree = navMode === 'software' ? SOFTWARE_TREE : BUSINESS_TREE

  return (
    <div className="flex h-full w-full bg-background">
      {/* Activity Bar — mode switcher */}
      <div className="w-[46px] shrink-0 border-r border-border/50 bg-muted/10 flex flex-col items-center py-3 gap-2">
        <button
          type="button"
          onClick={toggleSidebar}
          className="w-8 h-8 flex items-center justify-center rounded-md text-muted-foreground/60 hover:text-foreground hover:bg-muted/40 transition-colors mb-2"
          title={isSidebarExpanded ? t('sidebar.collapse', 'Collapse sidebar') : t('sidebar.expand', 'Expand sidebar')}
          aria-label="Toggle sidebar"
        >
          {isSidebarExpanded ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
        </button>

        <button
          type="button"
          onClick={() => setNavMode('software')}
          className={`w-8 h-8 flex items-center justify-center rounded-md transition-all duration-150 ${
            navMode === 'software'
              ? 'bg-primary/15 text-primary border border-primary/25'
              : 'text-muted-foreground/60 hover:text-foreground hover:bg-muted/40'
          }`}
          title={t('sidebar.software_aria')}
          aria-label={t('sidebar.software_aria')}
          aria-pressed={navMode === 'software'}
        >
          <Box className="w-4 h-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={() => setNavMode('business')}
          className={`w-8 h-8 flex items-center justify-center rounded-md transition-all duration-150 ${
            navMode === 'business'
              ? 'bg-primary/15 text-primary border border-primary/25'
              : 'text-muted-foreground/60 hover:text-foreground hover:bg-muted/40'
          }`}
          title={t('sidebar.business_aria')}
          aria-label={t('sidebar.business_aria')}
          aria-pressed={navMode === 'business'}
        >
          <LayoutDashboard className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>

      {/* Primary Sidebar content - Hidden when collapsed */}
      <div
        className={`flex-1 flex flex-col overflow-hidden transition-all duration-300 ease-in-out ${
          isSidebarExpanded ? 'opacity-100 min-w-[200px]' : 'opacity-0 min-w-0 flex-none w-0'
        }`}
      >
        {/* Sidebar header */}
        <div className="px-3 h-11 shrink-0 flex items-center justify-between">
          <h2 className="text-[10px] font-semibold tracking-[0.08em] text-muted-foreground/60 uppercase">
            {navMode === 'software' ? t('sidebar.software_header') : t('sidebar.business_header')}
          </h2>
          <button
            type="button"
            onClick={() => setActiveFunctionId(null)}
            className="w-6 h-6 flex items-center justify-center rounded-md text-muted-foreground/50 hover:text-foreground hover:bg-muted/50 transition-colors"
            title={t('sidebar.home_button')}
            aria-label={t('sidebar.home_button')}
          >
            <Home className="w-3 h-3" aria-hidden="true" />
          </button>
        </div>

        {/* Navigation tree */}
        <div className="flex-1 overflow-y-auto py-2 px-2 overflow-x-hidden">
          <AnimatePresence mode="wait">
            <motion.div
              key={navMode}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 8 }}
              transition={{ duration: 0.12, ease: 'easeInOut' }}
            >
              {tree.map(section => {
                const isExpanded = expandedSections[section.titleKey]
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const title = t(section.titleKey as any) as string
                return (
                  <div key={section.titleKey} className="mb-1">
                    <button
                      type="button"
                      onClick={() => toggleSection(section.titleKey)}
                      className="flex items-center w-full px-2 py-1.5 rounded-md text-[12px] font-medium text-foreground/70 hover:text-foreground hover:bg-muted/40 transition-colors"
                      aria-expanded={isExpanded}
                      aria-controls={`section-${section.titleKey}`}
                    >
                      <span className="mr-1 text-muted-foreground/50" aria-hidden="true">
                        {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      </span>
                      <span className="mr-1.5 text-muted-foreground/60" aria-hidden="true">{section.icon}</span>
                      <span className="truncate flex-1 text-left">{title}</span>
                    </button>
                    <AnimatePresence initial={false}>
                      {isExpanded && (
                        <motion.div
                          id={`section-${section.titleKey}`}
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.18, ease: [0.25, 0.1, 0.25, 1] }}
                          className="mt-0.5 overflow-hidden"
                        >
                          {section.items.map(item => (
                            <button
                              key={item.id}
                              type="button"
                              onClick={() => setActiveFunctionId(item.id as FunctionId)}
                              className={`flex items-center w-full pl-6 pr-2 py-1.5 text-[12px] rounded-md transition-all duration-100 ${
                                activeFunctionId === item.id
                                  ? 'bg-primary/10 text-primary font-medium border-l-2 border-primary pl-[22px]'
                                  : 'text-muted-foreground/70 hover:text-foreground hover:bg-muted/40'
                              }`}
                            >
                              <span className="truncate flex-1 text-left">
                                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                                {t(item.labelKey as any) as string}
                              </span>
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

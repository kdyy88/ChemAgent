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
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useWorkspaceStore, type NavMode, type FunctionId } from '@/store/workspaceStore'
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

  const initialExpanded = Object.fromEntries(
    [...SOFTWARE_TREE, ...BUSINESS_TREE].map((s) => [s.titleKey, true])
  )
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>(initialExpanded)

  const toggleSection = (key: string) => {
    setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const tree = navMode === 'software' ? SOFTWARE_TREE : BUSINESS_TREE

  return (
    <div className="flex h-full bg-background border-r">
      {/* Activity Bar */}
      <div className="w-[50px] shrink-0 border-r bg-muted/30 flex flex-col items-center py-4 gap-4">
        <button
          type="button"
          onClick={() => setNavMode('software')}
          className={`p-2.5 rounded-lg transition-colors ${navMode === 'software' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
          title={t('sidebar.software_aria')}
          aria-label={t('sidebar.software_aria')}
          aria-pressed={navMode === 'software'}
        >
          <Box className="w-5 h-5" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={() => setNavMode('business')}
          className={`p-2.5 rounded-lg transition-colors ${navMode === 'business' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
          title={t('sidebar.business_aria')}
          aria-label={t('sidebar.business_aria')}
          aria-pressed={navMode === 'business'}
        >
          <LayoutDashboard className="w-5 h-5" aria-hidden="true" />
        </button>
      </div>

      {/* Primary Sidebar */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-4 py-3 border-b shrink-0 flex items-center justify-between h-[49px]">
          <h2 className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
            {navMode === 'software' ? t('sidebar.software_header') : t('sidebar.business_header')}
          </h2>
          <button
            type="button"
            onClick={() => setActiveFunctionId(null)}
            className="p-1.5 hover:bg-muted/80 rounded-md text-muted-foreground hover:text-foreground transition-colors"
            title={t('sidebar.home_button')}
            aria-label={t('sidebar.home_button')}
          >
            <Home className="w-3.5 h-3.5" aria-hidden="true" />
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
                const isExpanded = expandedSections[section.titleKey]
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const title = t(section.titleKey as any) as string
                return (
                  <div key={section.titleKey} className="mb-2">
                    <button
                      type="button"
                      onClick={() => toggleSection(section.titleKey)}
                      className="flex items-center w-full px-1.5 py-1.5 text-sm font-medium text-foreground hover:bg-muted/50 rounded-md transition-colors"
                      aria-expanded={isExpanded}
                      aria-controls={`section-${section.titleKey}`}
                    >
                      <span className="mr-1 text-muted-foreground" aria-hidden="true">
                        {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      </span>
                      <span className="mr-1.5 text-muted-foreground" aria-hidden="true">{section.icon}</span>
                      <span className="truncate flex-1 text-left">{title}</span>
                    </button>
                    <AnimatePresence initial={false}>
                      {isExpanded && (
                        <motion.div
                          id={`section-${section.titleKey}`}
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          className="mt-1 overflow-hidden"
                        >
                          {section.items.map(item => (
                            <button
                              key={item.id}
                              type="button"
                              onClick={() => setActiveFunctionId(item.id as FunctionId)}
                              className={`flex items-center w-full pl-6 pr-2 py-1.5 text-xs rounded-md transition-colors ${activeFunctionId === item.id ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground hover:bg-muted text-foreground'}`}
                            >
                              <span className="truncate flex-1 text-left">
                               // eslint-disable-next-line @typescript-eslint/no-explicit-any
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

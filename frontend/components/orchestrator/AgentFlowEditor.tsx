'use client'

// Waldiez CSS is imported here (not in globals.css) so it only loads on the
// /workflow route and never pollutes the main chat page styles.
import '@waldiez/react/dist/@waldiez.css'

import { useEffect, useRef, useState } from 'react'
import { Waldiez, importFlow } from '@waldiez/react'
import type { WaldiezProps } from '@waldiez/react'

const STORAGE_KEY = 'chem-agent-waldiez-flow'
const FLOW_ID = 'chem-agent-flow-0'
const STORAGE_ID = 'chem-agent-storage-0'
const DEFAULT_NAME = 'ChemAgent Workflow'

function downloadJson(filename: string, content: string) {
  const blob = new Blob([content], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export default function AgentFlowEditor() {
  const [flowProps, setFlowProps] = useState<Partial<WaldiezProps> | null>(null)
  const initialized = useRef(false)

  // Load persisted flow from localStorage on mount
  useEffect(() => {
    if (initialized.current) return
    initialized.current = true

    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        const imported = importFlow(parsed)
        setFlowProps(imported)
        return
      } catch {
        // corrupted data — fall through to empty flow
        localStorage.removeItem(STORAGE_KEY)
      }
    }
    setFlowProps({})
  }, [])

  const handleSave = (flowJson: string) => {
    localStorage.setItem(STORAGE_KEY, flowJson)
  }

  // onConvert receives the flow JSON string.
  // Compiling to .py requires the Python waldiez exporter (backend).
  // For now we download the raw .json so the user can inspect or POST it later.
  const handleConvert = (flowJson: string, _to: 'py' | 'ipynb') => {
    const name = DEFAULT_NAME.toLowerCase().replace(/\s+/g, '-')
    downloadJson(`${name}.waldiez.json`, flowJson)
  }

  if (flowProps === null) {
    return (
      <div className="w-full h-[calc(100vh-64px)] flex items-center justify-center text-muted-foreground text-sm">
        Loading editor…
      </div>
    )
  }

  return (
    // Explicit pixel-bounded container — React Flow measures this div directly.
    // flex-1 alone (without a bounded parent) collapses to 0px height.
    <div className="w-full h-[calc(100vh-64px)]">
      <Waldiez
        flowId={FLOW_ID}
        storageId={STORAGE_ID}
        name={DEFAULT_NAME}
        description="Visual multi-agent workflow editor for ChemAgent"
        tags={['chemistry', 'ag2', 'multi-agent']}
        requirements={[]}
        nodes={(flowProps as WaldiezProps).nodes ?? []}
        edges={(flowProps as WaldiezProps).edges ?? []}
        viewport={(flowProps as WaldiezProps).viewport}
        onSave={handleSave}
        onConvert={handleConvert}
      />
    </div>
  )
}

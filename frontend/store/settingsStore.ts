/**
 * settingsStore — lightweight Zustand store for per-agent model preferences.
 * Extracted from chatStore so nothing here needs a WebSocket connection.
 * AgentModelConfig keys: manager, visualizer, researcher, analyst
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AgentModelConfig } from '@/lib/types'

interface SettingsState {
  agentModels: AgentModelConfig
  setAgentModels: (config: AgentModelConfig) => void
}

const DEFAULT_MODELS: AgentModelConfig = {
  manager: 'gpt-4o-mini',
  visualizer: 'gpt-4o-mini',
  researcher: 'gpt-4o-mini',
  analyst: 'gpt-4o-mini',
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      agentModels: DEFAULT_MODELS,
      setAgentModels: (config) => set({ agentModels: config }),
    }),
    { name: 'chemagent_model_prefs' },
  ),
)

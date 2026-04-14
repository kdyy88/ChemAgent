/**
 * uiStore — global application mode (Copilot ↔ Agent).
 *
 * Persisted to localStorage so the user's last choice survives page reloads.
 * Key exported: `useUIStore`, `AppMode`
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type AppMode = 'copilot' | 'agent'

interface UIState {
  appMode: AppMode
  setMode: (mode: AppMode) => void
  skillsEnabled: boolean
  toggleSkills: () => void
  isSidebarExpanded: boolean
  toggleSidebar: () => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      appMode: 'copilot',
      setMode: (mode) => set({ appMode: mode }),
      skillsEnabled: false,
      toggleSkills: () => set((s) => ({ skillsEnabled: !s.skillsEnabled })),
      isSidebarExpanded: true,
      toggleSidebar: () => set((s) => ({ isSidebarExpanded: !s.isSidebarExpanded })),
    }),
    { name: 'chemagent-ui-mode' },
  ),
)

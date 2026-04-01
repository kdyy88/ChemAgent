/**
 * i18nStore — Zustand store for user language preference.
 *
 * Responsibilities:
 * - Persist the user's chosen locale in localStorage (survives page refresh)
 * - Sync with i18next so both the React rendering layer and the imperative
 *   translation calls (e.g. in sse-client) always use the same language
 * - Expose a `setLocale()` action that redirects to the locale-prefixed URL
 *   so the Next.js middleware cookie is updated as well
 *
 * Usage in a Client Component:
 *   const { locale, setLocale } = useI18nStore()
 *   <button onClick={() => setLocale('en')}>English</button>
 *
 * The store is intentionally NOT used for the initial locale detection — that
 * is the middleware's job. This store only handles voluntary language switches
 * initiated by the user after the page has loaded.
 */

'use client'

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { DEFAULT_LOCALE, SUPPORTED_LOCALES, type Locale } from '@/lib/i18n/config'

interface I18nState {
  /** The currently active locale — kept in sync with i18next and the URL. */
  locale: Locale

  /**
   * Switch language.
   * - Updates the Zustand state + localStorage
   * - Calls i18next.changeLanguage() for immediate UI re-render
   * - Navigates to the new locale-prefixed path so the middleware updates the cookie
   */
  setLocale: (locale: Locale) => void
}

export const useI18nStore = create<I18nState>()(
  persist(
    (set) => ({
      locale: DEFAULT_LOCALE,

      setLocale: (nextLocale) => {
        if (!SUPPORTED_LOCALES.includes(nextLocale)) return

        set({ locale: nextLocale })

        // Sync i18next imperatively (safe to call on the client only)
        if (typeof window !== 'undefined') {
          // Dynamic import avoids loading the singleton during SSR
          import('@/lib/i18n/client').then(({ default: i18n }) => {
            if (i18n.language !== nextLocale) {
              i18n.changeLanguage(nextLocale)
            }
          })

          // Navigate to the locale-prefixed version of the current path.
          // e.g. /zh/workflow  →  /en/workflow
          const currentPath = window.location.pathname
          const segments = currentPath.split('/')
          // segments[1] is the current locale segment (set by middleware)
          const localeIndex = SUPPORTED_LOCALES.find((l) => l === segments[1]) ? 1 : null
          const pathWithoutLocale =
            localeIndex !== null ? '/' + segments.slice(2).join('/') : currentPath

          const newPath = `/${nextLocale}${pathWithoutLocale || ''}${window.location.search}`
          window.history.pushState({}, '', newPath)
        }
      },
    }),
    {
      name: 'chemagent-locale',
      storage: createJSONStorage(() => localStorage),
      // Only persist the locale value — actions are not serializable
      partialize: (state) => ({ locale: state.locale }),
    },
  ),
)

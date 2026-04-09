/**
 * Client-side i18n singleton for Next.js Client Components.
 *
 * Initializes once and reuses the same i18next instance across the app.
 * Translations are loaded on-demand (per namespace) via dynamic imports —
 * so only the namespaces the user's active page needs are fetched over the network.
 *
 * Usage in a Client Component:
 *   'use client'
 *   import { useTranslation } from 'react-i18next'
 *   import '@/lib/i18n/client'   // ensures the singleton is initialized
 *
 *   export function MyComponent() {
 *     const { t } = useTranslation('chemistry')
 *     return <span>{t('molecule_weight')}</span>
 *   }
 */

import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'
import resourcesToBackend from 'i18next-resources-to-backend'
import LanguageDetector from 'i18next-browser-languagedetector'
import { DEFAULT_LOCALE, DEFAULT_NS, LOCALE_COOKIE, SUPPORTED_LOCALES } from './config'
import type {} from './types'

// Guard: only initialize once (hot-reload safe in dev mode)
if (!i18next.isInitialized) {
  i18next
    .use(LanguageDetector)
    .use(initReactI18next)
    .use(
      // Lazy-loads individual namespace JSON files as dynamic imports.
      // Next.js will code-split these into separate chunks automatically.
      resourcesToBackend(
        (language: string, namespace: string) =>
          import(`../../public/locales/${language}/${namespace}.json`),
      ),
    )
    .init({
      supportedLngs: SUPPORTED_LOCALES,
      fallbackLng: DEFAULT_LOCALE,
      defaultNS: DEFAULT_NS,
      ns: [],   // No eager load — namespaces are loaded on first useTranslation() call
      interpolation: { escapeValue: false },
      react: {
        useSuspense: false,  // Avoid SSR Suspense mismatch
      },
      detection: {
        // Precedence: cookie → navigator → htmlTag
        order: ['cookie', 'navigator', 'htmlTag'],
        lookupCookie: LOCALE_COOKIE,
        caches: ['cookie'],
        cookieOptions: { path: '/', sameSite: 'lax' },
      },
    })
}

export default i18next

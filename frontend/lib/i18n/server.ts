/**
 * Server-side i18n initializer for Next.js Server Components.
 *
 * Each Server Component call that needs translations should call `getI18n(lang)`
 * which creates an isolated i18next instance — safe for concurrent SSR requests.
 *
 * Example:
 *   // app/[lang]/page.tsx  (Server Component)
 *   const { t } = await getI18n(params.lang)
 *   return <h1>{t('chat.empty_state')}</h1>
 */

import { createInstance } from 'i18next'
import resourcesToBackend from 'i18next-resources-to-backend'
import { DEFAULT_LOCALE, DEFAULT_NS, I18N_NAMESPACES, isSupportedLocale, type Locale } from './config'
import type {} from './types'

async function initServerI18n(locale: Locale, namespaces: readonly string[]) {
  const i18nInstance = createInstance()

  await i18nInstance
    .use(
      resourcesToBackend(
        (language: string, namespace: string) =>
          import(`../../public/locales/${language}/${namespace}.json`),
      ),
    )
    .init({
      lng: locale,
      ns: namespaces,
      defaultNS: DEFAULT_NS,
      fallbackLng: DEFAULT_LOCALE,
      fallbackNS: DEFAULT_NS,
      interpolation: { escapeValue: false },
      // Disable debug in production
      debug: process.env.NODE_ENV === 'development' && process.env.I18N_DEBUG === 'true',
    })

  return i18nInstance
}

/**
 * Returns an isolated i18next instance for the given locale.
 * All namespaces are pre-loaded so server components don't need to await per-key.
 */
export async function getI18n(lang?: string | null) {
  const locale = isSupportedLocale(lang ?? '') ? (lang as Locale) : DEFAULT_LOCALE
  const instance = await initServerI18n(locale, I18N_NAMESPACES)
  return {
    t: instance.t.bind(instance),
    i18n: instance,
    locale,
  }
}

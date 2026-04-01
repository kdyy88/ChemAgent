'use client'

/**
 * I18nProvider — Client Component that bridges the locale from the URL
 * (extracted by the Server Layout) into the i18next singleton.
 *
 * Why this is needed:
 *  - The i18next client singleton is initialized once on page load.
 *  - If the user navigates to a different locale URL (e.g. /en → /zh), or if
 *    the server-rendered HTML uses a different locale than the singleton's
 *    default, this provider syncs the language.
 *  - It also sets the document lang attribute for accessibility.
 */

import { type ReactNode, useEffect } from 'react'
import { I18nextProvider } from 'react-i18next'
import i18next from '@/lib/i18n/client'
import type { Locale } from '@/lib/i18n/config'

interface I18nProviderProps {
  locale: Locale
  children: ReactNode
}

export function I18nProvider({ locale, children }: I18nProviderProps) {
  useEffect(() => {
    if (i18next.language !== locale) {
      i18next.changeLanguage(locale)
    }
    document.documentElement.lang = locale
  }, [locale])

  return <I18nextProvider i18n={i18next}>{children}</I18nextProvider>
}

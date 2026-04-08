/**
 * Shared i18n configuration — consumed by both server and client instances.
 * Keep this file free of browser/Node-specific APIs so it can be imported
 * from middleware, server components, and client components alike.
 */

export const SUPPORTED_LOCALES = ['zh', 'en'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

export const DEFAULT_LOCALE: Locale = 'zh'
export const LOCALE_COOKIE = 'NEXT_LOCALE'

export const I18N_NAMESPACES = ['common', 'chemistry', 'agent'] as const
export type Namespace = (typeof I18N_NAMESPACES)[number]

export const DEFAULT_NS: Namespace = 'common'

/** Locale metadata for rendering language-switcher UIs. */
export const LOCALE_META: Record<Locale, { label: string; dir: 'ltr' | 'rtl' }> = {
  zh: { label: '中文', dir: 'ltr' },
  en: { label: 'English', dir: 'ltr' },
}

export function isSupportedLocale(lang: string): lang is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(lang)
}

/**
 * Extracts the locale segment from a URL pathname.
 * e.g. "/zh/chat" → "zh"  |  "/unknown/page" → null
 */
export function getLocaleFromPathname(pathname: string): Locale | null {
  const segment = pathname.split('/')[1]
  return isSupportedLocale(segment) ? segment : null
}

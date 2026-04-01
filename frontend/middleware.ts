/**
 * Next.js 15 i18n Middleware
 *
 * Responsibilities:
 * 1. Detect the user's preferred locale from:
 *    a) The NEXT_LOCALE cookie (explicit user preference)
 *    b) The Accept-Language request header
 *    c) Fallback to the configured DEFAULT_LOCALE
 * 2. Redirect URLs without a locale prefix to their locale-prefixed equivalent.
 *    e.g. GET /workflow  →  302  /zh/workflow
 * 3. Set the NEXT_LOCALE cookie on every response so the detected locale is
 *    remembered across sessions without requiring the user to log in.
 *
 * URLs that already have a valid locale prefix pass through unchanged.
 * Static files (_next/*, public assets, favicon) are always excluded.
 */

import { type NextRequest, NextResponse } from 'next/server'
import {
  DEFAULT_LOCALE,
  LOCALE_COOKIE,
  getLocaleFromPathname,
  isSupportedLocale,
  type Locale,
} from '@/lib/i18n/config'

/** Parse the best-matching locale from an Accept-Language header value. */
function detectLocaleFromHeader(acceptLanguage: string | null): Locale {
  if (!acceptLanguage) return DEFAULT_LOCALE

  // Split "zh-CN,zh;q=0.9,en;q=0.8" → ["zh-CN", "zh", "en"]
  const candidates = acceptLanguage
    .split(',')
    .map((entry) => {
      const [tag, q] = entry.trim().split(';q=')
      return { tag: tag.trim().toLowerCase(), weight: q ? parseFloat(q) : 1.0 }
    })
    .sort((a, b) => b.weight - a.weight)
    .map(({ tag }) => tag)

  for (const tag of candidates) {
    // Exact match: "zh" or "en"
    if (isSupportedLocale(tag)) return tag
    // Language prefix match: "zh-CN" → "zh", "en-US" → "en"
    const prefix = tag.split('-')[0]
    if (isSupportedLocale(prefix)) return prefix
  }

  return DEFAULT_LOCALE
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // ── Skip non-page assets ──────────────────────────────────────────────────
  if (
    pathname.startsWith('/_next') ||
    pathname.startsWith('/api') ||
    pathname.includes('.') // static files: .ico, .png, .svg, etc.
  ) {
    return NextResponse.next()
  }

  // ── Already locale-prefixed? ──────────────────────────────────────────────
  const existingLocale = getLocaleFromPathname(pathname)
  if (existingLocale) {
    // Refresh the cookie so it reflects the current URL locale
    const response = NextResponse.next()
    response.cookies.set(LOCALE_COOKIE, existingLocale, {
      path: '/',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 365, // 1 year
    })
    return response
  }

  // ── Detect target locale ──────────────────────────────────────────────────
  const cookieLocale = request.cookies.get(LOCALE_COOKIE)?.value
  const locale: Locale = isSupportedLocale(cookieLocale ?? '')
    ? (cookieLocale as Locale)
    : detectLocaleFromHeader(request.headers.get('Accept-Language'))

  // ── Redirect to locale-prefixed URL ──────────────────────────────────────
  const localeUrl = new URL(
    `/${locale}${pathname === '/' ? '' : pathname}${request.nextUrl.search}`,
    request.url,
  )

  const response = NextResponse.redirect(localeUrl, { status: 307 })
  response.cookies.set(LOCALE_COOKIE, locale, {
    path: '/',
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 365,
  })
  return response
}

export const config = {
  // Run on all routes except internal Next.js paths and static assets
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js|woff2?|ttf|eot)).*)',
  ],
}

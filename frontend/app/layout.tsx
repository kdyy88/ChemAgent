/**
 * Root layout — intentionally minimal.
 *
 * All providers (<html>, <body>, ThemeProvider, I18nProvider, …) live inside
 * app/[lang]/layout.tsx so that the locale segment can be read from route
 * params and applied to the <html lang="…"> attribute.
 *
 * This root layout exists only because Next.js requires one; it simply passes
 * children through.  The middleware (middleware.ts) ensures every request
 * is redirected to a locale-prefixed path (/zh/… or /en/…) before reaching
 * a page, so this wrapper is never used directly in practice.
 */

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return children
}

import { cookies } from 'next/headers'
import { DEFAULT_LOCALE, LOCALE_COOKIE, isSupportedLocale } from '@/lib/i18n/config'

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const cookieStore = await cookies()
  const cookieLocale = cookieStore.get(LOCALE_COOKIE)?.value
  const lang = isSupportedLocale(cookieLocale ?? '') ? cookieLocale : DEFAULT_LOCALE

  return (
    <html lang={lang} suppressHydrationWarning>
      <body>{children}</body>
    </html>
  )
}

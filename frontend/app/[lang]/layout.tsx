import type { Metadata } from 'next'
import { Geist, Geist_Mono, Syne } from 'next/font/google'
import { ThemeProvider } from 'next-themes'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ProgressBarProvider } from '@/components/providers/ProgressBarProvider'
import { QueryProvider } from '@/components/providers/QueryProvider'
import { I18nProvider } from '@/components/providers/I18nProvider'
import { isSupportedLocale, DEFAULT_LOCALE, SUPPORTED_LOCALES, type Locale } from '@/lib/i18n/config'
import { getI18n } from '@/lib/i18n/server'
import '../globals.css'

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] })
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] })
const syne = Syne({
  variable: '--font-syne',
  subsets: ['latin'],
  weight: ['400', '500', '600', '700', '800'],
})

// Generate static paths for all supported locales
export function generateStaticParams() {
  return SUPPORTED_LOCALES.map((lang) => ({ lang }))
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ lang: string }>
}): Promise<Metadata> {
  const { lang } = await params
  const { t } = await getI18n(lang)
  return {
    title: t('app.title'),
    description: t('app.description'),
  }
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ lang: string }>
}) {
  const { lang } = await params
  const locale: Locale = isSupportedLocale(lang) ? lang : DEFAULT_LOCALE

  return (
    <div className={`${geistSans.variable} ${geistMono.variable} ${syne.variable} antialiased`}>
      <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
        <QueryProvider>
          <ProgressBarProvider>
            <TooltipProvider>
              <I18nProvider locale={locale}>{children}</I18nProvider>
            </TooltipProvider>
          </ProgressBarProvider>
        </QueryProvider>
      </ThemeProvider>
    </div>
  )
}

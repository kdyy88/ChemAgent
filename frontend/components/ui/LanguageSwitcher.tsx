'use client'

/**
 * LanguageSwitcher — dropdown for switching the active locale.
 *
 * On first visit the locale is already auto-detected by the middleware
 * (Accept-Language header) and by the i18next LanguageDetector (navigator).
 * This component lets the user override that choice persistently via
 * the NEXT_LOCALE cookie + localStorage (i18nStore).
 */

import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Languages, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useI18nStore } from '@/store/i18nStore'
import { LOCALE_META, SUPPORTED_LOCALES, type Locale } from '@/lib/i18n/config'
import '@/lib/i18n/client'   // ensure singleton is initialized

export function LanguageSwitcher() {
  const { i18n } = useTranslation()
  const { locale, setLocale } = useI18nStore()

  // On mount: sync the store to whatever locale the browser/middleware detected
  // so the dropdown reflects the actual active language even before any click.
  useEffect(() => {
    const detected = i18n.language?.split('-')[0] as Locale
    const active = SUPPORTED_LOCALES.includes(detected) ? detected : locale
    if (active !== locale) {
      setLocale(active)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Tooltip>
      <DropdownMenu>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="relative text-muted-foreground hover:text-foreground"
              aria-label="Switch language"
            >
              <Languages className="h-4 w-4" aria-hidden="true" />
              {/* Show 2-letter locale badge */}
              <span className="absolute bottom-0.5 right-0.5 text-[8px] font-bold leading-none uppercase select-none pointer-events-none">
                {locale}
              </span>
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>

        <TooltipContent>
          {locale === 'zh' ? '切换语言' : 'Switch language'}
        </TooltipContent>

        <DropdownMenuContent align="end" className="min-w-[110px]">
          {SUPPORTED_LOCALES.map((lang) => (
            <DropdownMenuItem
              key={lang}
              onClick={() => setLocale(lang)}
              className="flex items-center justify-between gap-3 cursor-pointer"
            >
              <span>{LOCALE_META[lang].label}</span>
              {locale === lang && <Check className="h-3.5 w-3.5 text-primary" />}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </Tooltip>
  )
}

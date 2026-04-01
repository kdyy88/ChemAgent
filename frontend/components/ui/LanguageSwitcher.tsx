'use client'

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
import { useI18nStore } from '@/store/i18nStore'
import { LOCALE_META, SUPPORTED_LOCALES, type Locale } from '@/lib/i18n/config'
import '@/lib/i18n/client'

export function LanguageSwitcher() {
  const { i18n } = useTranslation()
  const { locale, setLocale } = useI18nStore()

  // Sync store to middleware/browser-detected locale on first mount
  useEffect(() => {
    const detected = i18n.language?.split('-')[0] as Locale
    const active = SUPPORTED_LOCALES.includes(detected) ? detected : locale
    if (active !== locale) {
      setLocale(active)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative text-muted-foreground hover:text-foreground"
          aria-label="Switch language"
        >
          <Languages className="h-4 w-4" aria-hidden="true" />
          <span className="absolute bottom-0.5 right-0.5 text-[8px] font-bold leading-none uppercase select-none pointer-events-none">
            {locale}
          </span>
        </Button>
      </DropdownMenuTrigger>

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
  )
}

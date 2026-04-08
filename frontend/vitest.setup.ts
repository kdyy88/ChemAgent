import '@testing-library/jest-dom'
import { vi } from 'vitest'

// Mock react-i18next so tests don't need loaded locale files.
// t('some.key') returns 'some.key' by default; tests may override as needed.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'en' },
  }),
  Trans: ({ i18nKey }: { i18nKey: string }) => i18nKey,
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}))

vi.mock('@/lib/i18n/client', () => ({
  default: { isInitialized: true, t: (key: string) => key, changeLanguage: vi.fn() },
}))


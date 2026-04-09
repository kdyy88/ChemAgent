/**
 * TypeScript type augmentation for i18next.
 *
 * Importing the English locale JSONs as the type source gives us:
 *  - Autocompletion for all translation keys
 *  - Compile-time errors for unknown keys
 *  - Type-safe interpolation with `t('common:errors.http_error', { status: 404 })`
 *
 * Usage:
 *   import type {} from '@/lib/i18n/types'  // triggers augmentation
 *   const { t } = useTranslation('chemistry')
 *   t('molecule_weight')   // ✅ type-checked
 *   t('chemistry:tool.validate_smiles')  // ✅ cross-namespace
 */

import 'i18next'

import type commonEn from '../../public/locales/en/common.json'
import type chemistryEn from '../../public/locales/en/chemistry.json'
import type agentEn from '../../public/locales/en/agent.json'

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'common'
    resources: {
      common: typeof commonEn
      chemistry: typeof chemistryEn
      agent: typeof agentEn
    }
  }
}

import { useTranslation } from 'react-i18next'
import { fmtNumber } from '@/utils/persianLocale'

/**
 * Renders a Polymind Credits count for non-$ viewers (normal users). Mirrors
 * `CostValue`'s contract EXACTLY: shows `fallback` (em-dash) for
 * null/undefined/NaN, `tabular-nums`, digit-script aware via `fmtNumber`. The
 * localized unit comes from `billing:credits.suffix` ("{{value}} credits" /
 * "{{value}} اعتبار").
 *
 * Pair with `CostValue` behind `canSeePrice` (utils/money): price viewers get
 * `<CostValue/>`, everyone else gets `<CreditValue/>`.
 */
export function CreditValue({
  credits,
  fallback = '—',
  className = '',
  suffixKey = 'credits.suffix',
}) {
  const { t } = useTranslation('billing')
  if (credits == null || Number.isNaN(Number(credits))) {
    return <span className={className}>{fallback}</span>
  }
  const label = t(suffixKey, { value: fmtNumber(Number(credits), { decimals: 0 }) })
  return <span className={`tabular-nums ${className}`.trim()}>{label}</span>
}

export default CreditValue

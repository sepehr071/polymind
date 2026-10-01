import { fmtCurrency } from '@/utils/persianLocale'

/**
 * Renders a USD cost, localised to the active UI language (Persian digits for
 * `fa`). Shows `fallback` (em-dash) for null/undefined/NaN. Digit formatting is
 * delegated to `fmtCurrency`, whose `Intl.NumberFormat` instances are memoised
 * at module scope — so a table of hundreds of cost cells builds no formatter
 * per render.
 */
export function CostValue({ usd, fallback = '—', className = '' }) {
  if (usd == null || Number.isNaN(Number(usd))) {
    return <span className={className}>{fallback}</span>
  }
  return (
    <span className={`tabular-nums ${className}`.trim()}>{fmtCurrency(Number(usd))}</span>
  )
}

export default CostValue

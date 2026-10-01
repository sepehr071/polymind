import { useTranslation } from 'react-i18next'
import { METRICS } from './metrics'
import { cn } from '@/lib/utils'

/**
 * Segmented control selecting the active time-series metric (cost / calls /
 * tokens / active users). A radiogroup so arrow keys + screen readers work.
 * Cost is omitted when `costVisible` is false (masked tier).
 *
 * @param {string} value
 * @param {(key:string)=>void} onChange
 * @param {boolean} [costVisible]
 */
export function MetricToggle({ value, onChange, costVisible = true, className }) {
  const { t } = useTranslation('analytics')
  const options = METRICS.filter((m) => costVisible || !m.costSensitive)

  return (
    <div
      role="radiogroup"
      aria-label={t('metrics.label', 'Metric')}
      className={cn(
        'inline-flex items-center gap-0.5 rounded-lg border border-border bg-background-secondary p-0.5',
        className,
      )}
    >
      {options.map((m) => {
        const active = value === m.key
        const Icon = m.icon
        return (
          <button
            key={m.key}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange?.(m.key)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              active
                ? 'bg-accent-muted text-accent'
                : 'text-foreground-tertiary hover:text-foreground',
            )}
          >
            <Icon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden />
            <span className="hidden sm:inline">{t(`metrics.${m.i18nKey}`)}</span>
          </button>
        )
      })}
    </div>
  )
}

export default MetricToggle

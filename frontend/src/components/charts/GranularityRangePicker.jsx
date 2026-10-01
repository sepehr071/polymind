import { memo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { CalendarDays } from 'lucide-react'
import { fmtDate } from '@/utils/dateLocale'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

const GRANULARITIES = ['day', 'week', 'month']

/**
 * Controlled granularity + date-range picker. Replaces the scattered 7/30/90
 * `<Select>`s across admin/platform dashboards with one control driving the
 * analytics envelope's `granularity` + `window.{from,to}`.
 *
 *   value:   { granularity: 'day'|'week'|'month', from: 'YYYY-MM-DD', to: 'YYYY-MM-DD' }
 *   onChange(nextValue)   — emits a NEW object on any field change
 *
 * Dates use native `<input type="date">` (value is the ISO `YYYY-MM-DD` string
 * the backend window expects) — no date-picker dep, fully keyboard-accessible,
 * and `dir="ltr"` locked because date inputs are inherently LTR. Labels come
 * from the `analytics` namespace with inline English fallbacks so the control
 * renders correctly before that JSON lands.
 *
 * @param {{granularity:string, from:string, to:string}} value
 * @param {(next:{granularity:string, from:string, to:string}) => void} onChange
 */
function GranularityRangePickerBase({ value, onChange, className, disabled = false }) {
  const { t } = useTranslation('analytics')
  const { granularity = 'day', from = '', to = '' } = value || {}

  const emit = useCallback(
    (patch) => onChange?.({ granularity, from, to, ...patch }),
    [onChange, granularity, from, to],
  )

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      <Select
        value={granularity}
        onValueChange={(g) => emit({ granularity: g })}
        disabled={disabled}
      >
        <SelectTrigger className="h-8 w-[110px] text-xs" aria-label={t('granularity.label', 'Granularity')}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {GRANULARITIES.map((g) => (
            <SelectItem key={g} value={g} className="text-xs">
              {t(`granularity.${g}`, g.charAt(0).toUpperCase() + g.slice(1))}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <div className="flex items-center gap-1.5 rounded-md border border-border bg-background-secondary px-2 py-1">
        <CalendarDays className="h-3.5 w-3.5 flex-shrink-0 text-foreground-tertiary" aria-hidden />
        <DateField
          value={from}
          max={to || undefined}
          disabled={disabled}
          ariaLabel={t('range.from', 'From')}
          onChange={(v) => emit({ from: v })}
        />
        <span className="text-foreground-tertiary" aria-hidden>
          –
        </span>
        <DateField
          value={to}
          min={from || undefined}
          disabled={disabled}
          ariaLabel={t('range.to', 'To')}
          onChange={(v) => emit({ to: v })}
        />
      </div>
    </div>
  )
}

function DateField({ value, min, max, disabled, ariaLabel, onChange }) {
  const label = value
    ? fmtDate(new Date(`${value}T00:00:00`), 'd MMMM yyyy')
    : '—'
  return (
    <label className="relative inline-flex min-w-[8.5rem] cursor-pointer items-center">
      <span className="pointer-events-none text-xs text-foreground">{label}</span>
      <input
        type="date"
        dir="ltr"
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-label={ariaLabel}
        className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
      />
    </label>
  )
}

export const GranularityRangePicker = memo(GranularityRangePickerBase)
export default GranularityRangePicker

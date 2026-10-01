import { useTranslation } from 'react-i18next'
import { fmtNumber } from '@/utils/persianLocale'

/**
 * RenderProgress — the OUTLINING and RENDERING stages share this indeterminate
 * progress surface. `progress` = { phase, done, total }; when total is known we
 * show a percentage, otherwise just the phase label. `warnings` (render stage
 * only) surfaces skipped images without failing the deck.
 *
 * The pulse uses the CSS-keyframe `.animate-pulse-dot` (index.css) rather than
 * framer-motion — per the house rule, framer `repeat:Infinity` can render dead
 * static and the global reduce-motion rule freezes CSS animations app-wide.
 */
export default function RenderProgress({ progress, label, warnings }) {
  const { t } = useTranslation('presentations')
  const total = Number(progress?.total)
  const done = Number(progress?.done)
  const pct =
    Number.isFinite(total) && total > 0 && Number.isFinite(done)
      ? Math.min(100, Math.round((done / total) * 100))
      : null
  const skipped = Array.isArray(warnings) ? warnings.length : 0

  return (
    <div className="space-y-3 py-12 text-center" dir="rtl" aria-live="polite" aria-busy="true">
      <div className="animate-pulse-dot inline-block size-3 rounded-full bg-primary" aria-hidden="true" />
      <div className="text-sm text-foreground">
        {label}
        {pct != null && (
          <span className="ms-1 tabular-nums text-foreground-secondary" dir="ltr">
            {fmtNumber(pct)}%
          </span>
        )}
      </div>
      {skipped > 0 && (
        <p className="text-xs text-foreground-tertiary">
          {typeof warnings[0] === 'string'
            ? warnings[warnings.length - 1]
            : t('phase.imagesSkipped', { count: skipped })}
        </p>
      )}
    </div>
  )
}

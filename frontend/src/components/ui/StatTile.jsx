import { memo } from 'react'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import { Card, CardContent } from '@/components/ui/card'
import { Sparkline } from '@/components/charts/Sparkline'
import { fmtNumber } from '@/utils/persianLocale'
import { useCountUp } from '@/hooks/useCountUp'

/** Default value formatter for `animateValue` — locale/numeral-aware integer. */
const defaultFormatValue = (n) => fmtNumber(n)

/**
 * Merged analytics stat tile — consolidates the per-page stat-tile variants
 * (admin + teams) into one primitive with an optional period-over-period
 * `delta` (arrow + %) and an inline `spark` trend.
 *
 * Material surface: composes the MUI Card (theme drives border/elevation/radius)
 * + MUI Typography for the label/value/subtitle. Semantic colors (success/error)
 * flow through the MUI palette so they auto-flip in dark mode and RTL.
 *
 * Delta semantics: `delta` is the fractional change for THIS metric vs the
 * previous window (e.g. `0.12` = +12%). `deltaDirection` decides which way is
 * "good" — for cost, a rise is usually neutral/bad; for active users a rise is
 * good. We color by sign × goodness:
 *   - 'up-good'   (default): + is success, − is error
 *   - 'down-good'           : − is success, + is error  (e.g. cost, errors)
 *   - 'neutral'             : never colors the delta (just shows direction)
 *
 * Pass `delta = null` to hide the trend row entirely (no previous window).
 *
 * Optional `animateValue` opts into an on-scroll count-up: when set, the tile
 * tweens 0 → `animateValue` (ease-out, respecting prefers-reduced-motion) and
 * renders `formatValue(count)` instead of `value`. Pass a RAW NUMBER (counts,
 * tokens) — NOT pre-masked / currency values. When omitted, `value` renders
 * verbatim (legacy, non-breaking).
 *
 * @param {React.ComponentType} icon         lucide icon
 * @param {React.ReactNode} label
 * @param {React.ReactNode} value
 * @param {number} [animateValue]            raw number to count up to (opt-in)
 * @param {(n:number)=>React.ReactNode} [formatValue]  formatter for the animated count (default `fmtNumber`)
 * @param {React.ReactNode} [subtitle]
 * @param {'positive'|'negative'} [tone]     overrides the VALUE color
 * @param {number|null} [delta]              fractional change (0.12 = +12%)
 * @param {'up-good'|'down-good'|'neutral'} [deltaDirection]
 * @param {number[]|object[]} [spark]        inline sparkline series
 * @param {number} [sparkColorIndex]         --chart-N slot for the spark
 */
function StatTileBase({
  icon: Icon,
  label,
  value,
  animateValue,
  formatValue = defaultFormatValue,
  subtitle,
  tone,
  delta = null,
  deltaDirection = 'up-good',
  spark,
  sparkColorIndex = 1,
  className,
}) {
  const valueColor =
    tone === 'positive' ? 'success.main' : tone === 'negative' ? 'error.main' : 'text.primary'

  // Opt-in count-up. The hook is always called (Rules of Hooks); its output is
  // only consumed when `animateValue` is a finite number, and its scroll-trigger
  // ref is only attached to the Card in that case. Legacy `value` path otherwise.
  const animated = typeof animateValue === 'number' && Number.isFinite(animateValue)
  const { count, ref: countRef } = useCountUp(animated ? animateValue : 0, 2000, true)
  const renderedValue = animated ? formatValue(count) : value

  const hasDelta = delta != null && Number.isFinite(Number(delta))
  const deltaNum = hasDelta ? Number(delta) : 0
  const rising = deltaNum > 0
  const flat = deltaNum === 0

  // sign × goodness → semantic MUI palette color
  let deltaColor = 'text.disabled'
  if (hasDelta && !flat && deltaDirection !== 'neutral') {
    const isGood = deltaDirection === 'up-good' ? rising : !rising
    deltaColor = isGood ? 'success.main' : 'error.main'
  }

  const DeltaIcon = flat ? Minus : rising ? ArrowUpRight : ArrowDownRight
  // |delta| as a percent string, digit-localized via fmtNumber.
  const deltaPct = `${fmtNumber(Math.abs(deltaNum) * 100, { decimals: 1 })}%`

  return (
    <Card ref={animated ? countRef : undefined} className={className}>
      <CardContent className="p-5">
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            color: 'text.disabled',
          }}
        >
          {Icon && <Icon className="h-3.5 w-3.5 flex-shrink-0" />}
          <Typography
            variant="overline"
            noWrap
            sx={{ lineHeight: 1.6, letterSpacing: '0.06em', color: 'inherit' }}
          >
            {label}
          </Typography>
        </Box>

        <Box sx={{ mt: 1, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 1.5 }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography
              variant="h5"
              sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums', color: valueColor }}
            >
              {renderedValue}
            </Typography>
            {subtitle && (
              <Typography variant="caption" sx={{ mt: 0.5, display: 'block', color: 'text.disabled' }}>
                {subtitle}
              </Typography>
            )}
          </Box>

          {spark && (
            <Box sx={{ width: 80, flexShrink: 0, alignSelf: 'center' }}>
              <Sparkline data={spark} colorIndex={sparkColorIndex} height={32} />
            </Box>
          )}
        </Box>

        {hasDelta && (
          <Box
            sx={{
              mt: 1,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 0.5,
              fontSize: '0.75rem',
              fontWeight: 600,
              color: deltaColor,
            }}
          >
            <DeltaIcon className="h-3.5 w-3.5" />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{deltaPct}</span>
          </Box>
        )}
      </CardContent>
    </Card>
  )
}

export const StatTile = memo(StatTileBase)
export default StatTile

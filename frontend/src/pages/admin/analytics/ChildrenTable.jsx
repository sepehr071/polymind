import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowDownRight, ArrowRight, ArrowUpRight, ChevronDown, Inbox, Minus } from 'lucide-react'
import { Sparkline } from '@/components/charts/Sparkline'
import { CostValue } from '@/components/ui/CostValue'
import { fmtNumber } from '@/utils/persianLocale'
import { cn } from '@/lib/utils'

/**
 * Rows are revealed in pages of this size. Each row mounts a live ECharts
 * `Sparkline` (canvas + ResizeObserver), so a holding drilldown with dozens of
 * children would otherwise mount dozens of chart instances at once. Capping the
 * rendered rows lazily mounts charts only as the user expands.
 */
const ROW_PAGE = 15

/**
 * Drilldown table for the envelope's `breakdown.children`. Each row is a button
 * (keyboard + click) navigating to `rowHref(child)`. Shows the localized
 * entity-kind label as the leading column, the four metrics, an inline trend
 * sparkline, and the period-over-period delta arrow.
 *
 * `delta_pct` is a percentage (12.5) or null; rendered as a signed % with a
 * direction arrow (neutral coloring — a usage rise isn't inherently good/bad).
 *
 * @param {Array<object>} children      envelope `breakdown.children`
 * @param {(child)=>string} rowHref     route for a row click
 * @param {string} nameLabel            header for the entity column
 * @param {boolean} [costVisible]
 * @param {boolean} [showActiveUsers]   include the active-users column (hidden for user-leaf parents)
 */
export function ChildrenTable({
  children,
  rowHref,
  nameLabel,
  costVisible = true,
  showActiveUsers = true,
  emptyLabel,
}) {
  const { t } = useTranslation('analytics')
  const navigate = useNavigate()
  const rows = Array.isArray(children) ? children : []

  const [visibleCount, setVisibleCount] = useState(ROW_PAGE)
  // Reset the cap when the row set changes (resort/refilter/navigation) so we
  // never strand the page mid-expansion against a different dataset.
  useEffect(() => {
    setVisibleCount(ROW_PAGE)
  }, [rows.length])

  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12 text-center text-foreground-tertiary">
        <span className="grid size-10 place-items-center rounded-full bg-background-tertiary">
          <Inbox className="h-4 w-4" aria-hidden />
        </span>
        <span className="text-sm">{emptyLabel || t('empty.breakdown')}</span>
      </div>
    )
  }

  // Cap applies after the parent's sort. Sparklines mount only for rendered rows.
  const visibleRows = rows.slice(0, visibleCount)
  const remaining = rows.length - visibleRows.length
  // Always-present columns: name, calls, tokens, trend, open (5) + optional cost/activeUsers.
  const colSpan = 5 + (costVisible ? 1 : 0) + (showActiveUsers ? 1 : 0)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-background-tertiary text-xs uppercase tracking-wide text-foreground-secondary">
          <tr>
            <th className="px-4 py-2.5 text-start font-bold">{nameLabel}</th>
            {costVisible && (
              <th className="px-4 py-2.5 text-end font-bold">{t('table.cost')}</th>
            )}
            <th className="px-4 py-2.5 text-end font-bold">{t('table.calls')}</th>
            <th className="px-4 py-2.5 text-end font-bold">{t('table.tokens')}</th>
            {showActiveUsers && (
              <th className="px-4 py-2.5 text-end font-bold">{t('table.activeUsers')}</th>
            )}
            <th className="px-4 py-2.5 text-center font-bold">{t('table.trend')}</th>
            <th className="px-4 py-2.5 text-end font-bold sr-only">{t('table.open')}</th>
          </tr>
        </thead>
        <tbody>
          {visibleRows.map((c) => {
            const href = rowHref?.(c)
            const dp = c.delta_pct
            const hasDelta = dp != null && Number.isFinite(Number(dp))
            const rising = Number(dp) > 0
            const flat = Number(dp) === 0
            const DeltaIcon = !hasDelta || flat ? Minus : rising ? ArrowUpRight : ArrowDownRight
            const go = () => href && navigate(href)
            return (
              <tr
                key={c.id}
                tabIndex={href ? 0 : -1}
                role={href ? 'link' : undefined}
                onClick={go}
                onKeyDown={(e) => {
                  if (href && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault()
                    go()
                  }
                }}
                className={cn(
                  'border-t border-border transition-colors',
                  href &&
                    'cursor-pointer hover:bg-background-tertiary/50 focus-visible:bg-background-tertiary/50 focus-visible:outline-none',
                )}
              >
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium text-foreground">{c.label}</span>
                  </div>
                </td>
                {costVisible && (
                  <td className="px-4 py-2.5 text-end tabular-nums">
                    <CostValue usd={c.cost} />
                  </td>
                )}
                <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary">
                  {fmtNumber(c.calls || 0)}
                </td>
                <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary">
                  {fmtNumber(c.tokens || 0)}
                </td>
                {showActiveUsers && (
                  <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary">
                    {fmtNumber(c.active_users || 0)}
                  </td>
                )}
                <td className="px-2 py-2.5">
                  <div className="mx-auto flex w-24 items-center justify-center">
                    <Sparkline data={c.spark} colorIndex={1} height={26} />
                  </div>
                </td>
                <td className="px-4 py-2.5 text-end">
                  <span className="inline-flex items-center justify-end gap-1.5">
                    {hasDelta && !flat && (
                      <span className="inline-flex items-center gap-0.5 text-xs tabular-nums text-foreground-tertiary">
                        <DeltaIcon className="h-3.5 w-3.5" aria-hidden />
                        {fmtNumber(Math.abs(Number(dp)), { decimals: 1 })}%
                      </span>
                    )}
                    {href && (
                      <ArrowRight
                        className="h-4 w-4 flex-shrink-0 text-foreground-tertiary rtl:rotate-180"
                        aria-hidden
                      />
                    )}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
        {remaining > 0 && (
          <tfoot>
            <tr className="border-t border-border">
              <td colSpan={colSpan} className="p-0">
                <button
                  type="button"
                  onClick={() => setVisibleCount((n) => n + ROW_PAGE)}
                  className="flex w-full items-center justify-center gap-1.5 px-4 py-2.5 text-xs font-medium text-foreground-tertiary transition-colors hover:bg-background-tertiary/50 hover:text-foreground-secondary focus-visible:bg-background-tertiary/50 focus-visible:outline-none"
                >
                  <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                  {t('table.showMore', { count: Math.min(remaining, ROW_PAGE) })}
                </button>
              </td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  )
}

export default ChildrenTable

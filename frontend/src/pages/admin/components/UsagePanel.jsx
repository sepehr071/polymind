import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { usageService } from '../../../services/usageService'
import Section from '@/components/teams/Section'
import { StatTile } from '@/components/ui/StatTile'
import { cn } from '../../../utils/cn'
import { CostValue } from '../../../components/ui/CostValue'
import { fmtNumber, fmtCurrencyCompact } from '@/utils/persianLocale'
import { BreakdownBarChart } from '@/components/charts'
import { prettifyModelName } from '@/utils/modelName'
import { originLabel } from '@/utils/originLabel'

function isoFromDaysAgo(days) {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString()
}

const GROUP_BY_KEYS = ['feature', 'model', 'day', 'user']

function formatTokens(val) {
  return fmtNumber(Number(val) || 0)
}

// `userId` (optional) scopes the breakdown to a single user — used by the admin
// per-user drilldown. When scoped, the `user` group-by is meaningless so it's
// dropped from the segmented control.
export default function UsagePanel({ userId = null }) {
  const { t } = useTranslation('admin')
  const { t: ta } = useTranslation('analytics')
  const [groupBy, setGroupBy] = useState('feature')

  const groupByKeys = useMemo(
    () => (userId ? GROUP_BY_KEYS.filter((k) => k !== 'user') : GROUP_BY_KEYS),
    [userId],
  )

  const filters = useMemo(() => ({
    from: isoFromDaysAgo(30),
    to: new Date().toISOString(),
    group_by: groupBy,
    ...(userId ? { user_id: userId } : {}),
  }), [groupBy, userId])

  const { data, isLoading, error } = useQuery({
    queryKey: ['usage', 'admin', userId, filters],
    queryFn: () => usageService.getAdminUsage(filters),
    staleTime: 60_000,
  })

  const rows = data?.data || []
  const totalCost = data?.total_cost ?? 0
  const totalTokens = data?.total_tokens ?? 0

  // Friendly label for a grouped key: models → prettified name, features →
  // origin label, day/user → raw key.
  const friendlyKey = (key) => {
    if (!key) return '—'
    if (groupBy === 'model') return prettifyModelName(key)
    if (groupBy === 'feature') return originLabel(key, ta)
    return key
  }

  const chartData = rows.map(r => ({
    label: friendlyKey(r.key),
    cost: Number(r.total_cost) || 0,
  }))

  const colLabel = groupBy === 'user'
    ? t('usage.user')
    : groupBy === 'day'
    ? t('usage.colDate')
    : groupBy === 'model'
    ? t('usage.model')
    : t('usage.feature')

  return (
    <div className="space-y-6">
      {/* Summary StatTiles — rendered OUTSIDE the panel (no card-in-card). */}
      <div className="grid grid-cols-2 gap-4">
        <StatTile label={t('usage.totalCost')} value={<CostValue usd={totalCost} />} />
        <StatTile label={t('usage.totalTokens')} value={formatTokens(totalTokens)} />
      </div>

      {/* Flat panel: group-by control + chart + breakdown table */}
      <Section
        title={t('usage.title')}
        padded={false}
        overflowVisible
        action={
          <Segmented
            value={groupBy}
            onChange={setGroupBy}
            options={groupByKeys.map((key) => ({ value: key, label: t(`usage.${key}`) }))}
            ariaLabel={t('usage.groupBy')}
          />
        }
      >
        <div className="space-y-6 p-4">
          {/* Loading / error / empty */}
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-accent" />
            </div>
          ) : error ? (
            <p className="text-error text-sm py-4">{t('usage.failedLoad')}</p>
          ) : rows.length === 0 ? (
            <div className="rounded-lg bg-background-secondary/50 p-8 text-center">
              <p className="text-foreground-secondary text-sm">{t('usage.noUsage')}</p>
            </div>
          ) : (
            <>
              {/* Chart */}
              <div className="rounded-lg bg-background-secondary/50 p-4" style={{ height: 248 }}>
                <BreakdownBarChart
                  data={chartData}
                  dataKey="cost"
                  labelKey="label"
                  topN={8}
                  valueFormatter={fmtCurrencyCompact}
                  metricLabel={t('usage.colCost')}
                  height="100%"
                />
              </div>

              {/* Breakdown table */}
              <div>
                <h3 className="font-medium text-foreground mb-3">
                  {groupBy === 'user' ? t('usage.perUserBreakdown') : t('usage.allEntries')}
                </h3>
                <div className="overflow-hidden rounded-2xl border border-border">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="bg-background-tertiary text-xs uppercase tracking-wide text-foreground-secondary">
                        <tr className="border-b border-border">
                          <th className="text-start py-2.5 px-3 font-bold">{colLabel}</th>
                          <th className="text-end py-2.5 px-3 font-bold">{t('usage.colCost')}</th>
                          <th className="text-end py-2.5 px-3 font-bold">{t('usage.colTokens')}</th>
                          <th className="text-end py-2.5 px-3 font-bold">{t('usage.colRequests')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row, i) => (
                          <tr key={i} className="border-t border-border/50 hover:bg-background-secondary/50 transition-colors">
                            <td className="py-2.5 px-3 text-foreground text-xs" title={row.key || ''}>{friendlyKey(row.key)}</td>
                            <td className="py-2.5 px-3 text-end text-foreground font-semibold tabular-nums">
                              <CostValue usd={row.total_cost} />
                            </td>
                            <td className="py-2.5 px-3 text-end text-foreground-secondary tabular-nums">{formatTokens(row.total_tokens)}</td>
                            <td className="py-2.5 px-3 text-end text-foreground-secondary tabular-nums">{fmtNumber(row.count ?? 0)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </Section>
    </div>
  )
}

/**
 * Canonical segmented filter (Consistent UI System): hover-bg container + 1px
 * line + radius11 + pad4; active = surface + small shadow, inactive fg2. Aligns
 * with the analytics MetricToggle pattern. A radiogroup for a11y.
 */
function Segmented({ value, onChange, options, ariaLabel }) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="inline-flex items-center gap-0.5 rounded-[11px] border border-border bg-background-tertiary p-1"
    >
      {options.map((opt) => {
        const active = value === opt.value
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              'rounded-lg px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              active
                ? 'bg-background text-foreground shadow-sm'
                : 'text-foreground-secondary hover:text-foreground',
            )}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}

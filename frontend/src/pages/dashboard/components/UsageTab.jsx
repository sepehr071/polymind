import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ArrowRight, Coins, Hash, Wallet } from 'lucide-react'
import { usageService } from '../../../services/usageService'
import { Separator } from '../../../components/ui/separator'
import { cn } from '../../../utils/cn'
import { CostValue } from '../../../components/ui/CostValue'
import { CreditValue } from '../../../components/ui/CreditValue'
import { canSeePriceInOrg, fmtCreditsShort } from '../../../utils/money'
import {
  calendarMonthRange,
  toApiWindow,
  isCalendarMonthRange,
  sumUsageRequests,
} from '../../../utils/usageWindow'
import { StatTile } from '../../../components/ui/StatTile'
import {
  ChartCard,
  TimeSeriesChart,
  BreakdownBarChart,
  GranularityRangePicker,
} from '../../../components/charts'
import { fmtNumber, fmtCurrency, fmtCurrencyCompact } from '../../../utils/persianLocale'
import { fmtDate } from '../../../utils/dateLocale'
import { prettifyModelName } from '../../../utils/modelName'
import { originLabel } from '../../../utils/originLabel'
import { useWorkspace } from '../../../context/WorkspaceContext'
import { useAuth } from '../../../context/AuthContext'

/** Localised short token count (1.2K / 3.4M). */
function fmtTokensShort(val) {
  const n = Number(val) || 0
  if (n >= 1_000_000) return `${fmtNumber(n / 1_000_000, { decimals: 1 })}M`
  if (n >= 1_000) return `${fmtNumber(n / 1_000, { decimals: 1 })}K`
  return fmtNumber(n)
}

/** Localise a `YYYY-MM-DD` bucket on the time axis / tooltip. */
function fmtBucketDate(iso) {
  if (!iso) return ''
  const d = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return fmtDate(d, 'MMM d')
}

/** ISO week start (Monday) for a date, as `YYYY-MM-DD`. */
function weekStartIso(d) {
  const x = new Date(d)
  if (Number.isNaN(x.getTime())) return String(d).slice(0, 10)
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7)) // Mon=0 … Sun=6
  // Serialize from LOCAL parts — toISOString() shifts to UTC, which moves the
  // local-midnight Monday onto the previous day for positive-offset timezones.
  const p = (n) => String(n).padStart(2, '0')
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}`
}

/**
 * Re-bucket a day-grained `[{date|key, cost, credits, tokens}]` series into the
 * chosen granularity. The personal-usage feed only emits daily rows, so
 * week/month granularity is an honest client-side roll-up of real daily data
 * (cost + credits + tokens summed, cost nulls preserved as "no visible cost").
 * Credits accumulate from 0 — every billable row carries a credit count, so
 * there's no "unknown credits" state to preserve as null.
 */
function rebucketDaily(daily, granularity) {
  const keyOf = (iso) => {
    if (granularity === 'month') return iso.slice(0, 7) // YYYY-MM
    if (granularity === 'week') return weekStartIso(`${iso}T00:00:00`)
    return iso
  }
  const buckets = new Map()
  for (const r of daily) {
    const iso = r.key || r.date
    if (!iso) continue
    const k = keyOf(iso)
    const prev = buckets.get(k) || { bucket: k, cost: null, credits: 0, tokens: 0 }
    const c = r.total_cost ?? r.cost
    if (c != null && !Number.isNaN(Number(c))) {
      prev.cost = (prev.cost ?? 0) + Number(c)
    }
    prev.credits += Number(r.credits) || 0
    prev.tokens += Number(r.total_tokens ?? r.tokens) || 0
    buckets.set(k, prev)
  }
  return [...buckets.values()].sort((a, b) =>
    a.bucket < b.bucket ? -1 : a.bucket > b.bucket ? 1 : 0,
  )
}

export default function UsageTab() {
  const { t } = useTranslation(['dashboard', 'analytics', 'billing'])
  // `originLabel` looks up bare `origin.*` keys, so it needs a t bound to the
  // analytics namespace (the multi-ns t above resolves `dashboard` first).
  const { t: tAnalytics } = useTranslation('analytics')
  const [groupBy, setGroupBy] = useState('feature')
  const [range, setRange] = useState(() => {
    const month = calendarMonthRange()
    return { granularity: 'day', from: month.from, to: month.to }
  })
  const { workspaces, currentWorkspace } = useWorkspace()
  const { user } = useAuth()
  const workspaceId = currentWorkspace?._id || null
  // Single source of truth (utils/money): admin or owner of the CURRENT org
  // sees $ price; everyone else sees Polymind Credits + token counts only.
  const priceVisible = canSeePriceInOrg(user, workspaces, workspaceId)
  // Cross-link to company billing: only for owners (or super-admin) of a real
  // team company — non-owners bounce from settings, so hide the dead-end link.
  const canOpenCompanyBilling =
    user?.role === 'admin' ||
    (currentWorkspace?.type === 'team' &&
      (currentWorkspace?.member_role === 'owner'))
  const companyBillingId =
    canOpenCompanyBilling && currentWorkspace
      ? currentWorkspace._id
      : null

  const GROUP_BY_OPTIONS = [
    { value: 'feature', label: t('usage.groupByFeature') },
    { value: 'model', label: t('usage.groupByModel') },
  ]

  // ISO window endpoints — the backend expects full timestamps; pin `to` to the
  // end of the chosen day so today's rows are included.
  const apiWindow = useMemo(() => {
    const month = calendarMonthRange()
    return toApiWindow({
      from: range.from || month.from,
      to: range.to || month.to,
    })
  }, [range.from, range.to])
  const monthWindow = isCalendarMonthRange(range.from, range.to)

  // Breakdown query — grouped by the user-selected dimension (feature|model).
  const breakdownQ = useQuery({
    queryKey: ['usage', 'me', 'breakdown', workspaceId, apiWindow.from, apiWindow.to, groupBy],
    queryFn: () =>
      usageService.getMyUsage({
        from: apiWindow.from,
        to: apiWindow.to,
        group_by: groupBy,
        workspace_id: workspaceId,
      }),
    enabled: !!workspaceId,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })

  // Daily time-series query — always grouped by day for the trend chart,
  // independent of the breakdown dimension.
  const dailyQ = useQuery({
    queryKey: ['usage', 'me', 'daily', workspaceId, apiWindow.from, apiWindow.to],
    queryFn: () =>
      usageService.getMyUsage({
        from: apiWindow.from,
        to: apiWindow.to,
        group_by: 'day',
        workspace_id: workspaceId,
      }),
    enabled: !!workspaceId,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })

  const isLoading = breakdownQ.isLoading || dailyQ.isLoading
  const error = breakdownQ.error || dailyQ.error

  // System-internal features (DLP content-safety, auto-title) are platform
  // costs, not user-driven actions — they're admin info. Strip them from the
  // breakdown for non-cost-visible (normal) users; admins/owners still see them.
  const rows = useMemo(() => {
    const raw = breakdownQ.data?.data || []
    if (priceVisible || groupBy !== 'feature') return raw
    return raw.filter((r) => r.key !== 'content_safety' && r.key !== 'auto_title')
  }, [breakdownQ.data, priceVisible, groupBy])
  // Preserve null/undefined so gated cost renders as '—', not '$0.00'.
  const totalCost = breakdownQ.data?.total_cost
  // Credits are always present in the payload (every billable row carries one);
  // default to 0 so the credits tile renders a real count, never '—'.
  const totalCredits = breakdownQ.data?.total_credits ?? 0
  const totalTokens = breakdownQ.data?.total_tokens ?? 0
  // Own per-user budget (when one is set for the current member). It renders a
  // remaining/limit in $, so it's gated to price viewers — a normal user must
  // never see a dollar figure (the backend exposes no credits form for it yet).
  const rawBudget = breakdownQ.data?.my_budget || null
  const myBudget = priceVisible ? rawBudget : null
  const totalRequests = useMemo(
    () =>
      sumUsageRequests(
        groupBy === 'feature' ? breakdownQ.data?.data : rows,
      ),
    [breakdownQ.data, rows, groupBy],
  )

  // Daily rows rolled up into the selected granularity. Each bucket carries
  // cost (price viewers), credits (everyone), and tokens; the chart plots one.
  const series = useMemo(
    () => rebucketDaily(dailyQ.data?.data || [], range.granularity),
    [dailyQ.data, range.granularity],
  )

  // Bucket-label formatter follows granularity: month → "Jun 2026", else a date.
  const bucketFormatter = useMemo(() => {
    if (range.granularity === 'month') {
      return (iso) => {
        if (!iso) return ''
        const d = new Date(`${iso}-01T00:00:00`)
        return Number.isNaN(d.getTime()) ? iso : fmtDate(d, 'MMM yyyy')
      }
    }
    return fmtBucketDate
  }, [range.granularity])

  // One series on the trend chart so the single Y axis stays meaningful: cost
  // when price-visible (the dominant owner/admin metric), Polymind Credits
  // otherwise (the headline metric for normal users). Cost/credits/tokens
  // differ by orders of magnitude, so the kit's single Y axis shows exactly one.
  const seriesMetrics = useMemo(
    () =>
      priceVisible
        ? [
            {
              key: 'cost',
              label: t('analytics:metrics.cost'),
              colorIndex: 1,
              formatter: (v) => fmtCurrency(Number(v) || 0),
            },
          ]
        : [
            {
              key: 'credits',
              label: t('usage.credits'),
              colorIndex: 2,
              formatter: (v) => fmtCreditsShort(v),
            },
          ],
    [priceVisible, t],
  )

  // Breakdown bars — by cost when price-visible, else by Polymind Credits (cost
  // would be a misleading flat zero for gated viewers).
  const breakdownKey = priceVisible ? 'cost' : 'credits'
  // Friendly row label: a clean model name for the 'model' dimension, a
  // localized origin label ("Chat"/"چت") for the 'feature' dimension.
  const labelFor = useMemo(
    () => (key) =>
      groupBy === 'model'
        ? prettifyModelName(key) || key || '—'
        : originLabel(key, tAnalytics) || key || '—',
    [groupBy, tAnalytics],
  )
  const breakdownRows = useMemo(
    () =>
      rows.map((r) => ({
        key: r.key,
        label: labelFor(r.key),
        cost: r.total_cost == null ? null : Number(r.total_cost),
        credits: Number(r.credits) || 0,
        tokens: Number(r.total_tokens) || 0,
      })),
    [rows, labelFor],
  )

  // Rank rows by the viewer's headline metric: cost (price viewers, null sorts
  // last) or Polymind Credits (everyone else). Keeps the "top spenders" table
  // honest for both tiers — credits track cost monotonically.
  const top5 = useMemo(
    () =>
      [...rows]
        .sort((a, b) => {
          if (priceVisible) {
            const av = a.total_cost == null ? -Infinity : Number(a.total_cost)
            const bv = b.total_cost == null ? -Infinity : Number(b.total_cost)
            return bv - av
          }
          return (Number(b.credits) || 0) - (Number(a.credits) || 0)
        })
        .slice(0, 5),
    [rows, priceVisible],
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-foreground-secondary">
          <span>{t('usage.orgScopeNote')}</span>
          {companyBillingId && (
            <Link
              to={`/workspaces/${companyBillingId}/settings?tab=billing`}
              className="inline-flex items-center gap-0.5 font-medium text-accent hover:underline"
            >
              {t('usage.viewCompanyBilling')}
              <ArrowRight className="h-3 w-3 rtl:-scale-x-100" />
            </Link>
          )}
        </p>
        <GranularityRangePicker value={range} onChange={setRange} />
      </div>

      {error ? (
        <p className="py-4 text-sm text-error">{t('usage.failedToLoad')}</p>
      ) : (
        <>
          <div
            className={cn(
              'grid gap-4',
              // Static class literals only — Tailwind JIT can't see `sm:grid-cols-${n}`.
              // A money tile (credits OR cost) is ALWAYS present now, alongside
              // tokens + requests; the budget tile is the only conditional one.
              myBudget ? 'sm:grid-cols-4' : 'sm:grid-cols-3',
            )}
          >
            {priceVisible ? (
              <StatTile
                icon={Coins}
                label={monthWindow ? t('usage.totalCost') : t('usage.consumption')}
                value={<CostValue usd={totalCost} />}
                tone="positive"
              />
            ) : (
              <StatTile
                icon={Coins}
                label={monthWindow ? t('usage.totalCredits') : t('usage.consumption')}
                value={<CreditValue credits={totalCredits} suffixKey="credits.jetonSuffix" />}
                tone="positive"
              />
            )}
            <StatTile
              icon={Hash}
              label={t('usage.totalTokens')}
              value={fmtTokensShort(totalTokens)}
              animateValue={totalTokens}
              formatValue={fmtTokensShort}
            />
            <StatTile
              label={t('usage.requests')}
              value={fmtNumber(totalRequests)}
              animateValue={totalRequests}
            />
            {myBudget && (
              <StatTile
                icon={Wallet}
                label={t('billing:myBudget.title')}
                value={<CostValue usd={myBudget.remaining} />}
                tone={Number(myBudget.remaining) < 0 ? 'negative' : 'positive'}
                subtitle={t('billing:myBudget.remaining', {
                  amount: fmtCurrency(Number(myBudget.amount_usd) || 0),
                })}
              />
            )}
          </div>

          <ChartCard
            title={t('analytics:chart.usageOverTime')}
            loading={isLoading}
            empty={series.length < 2}
            emptyLabel={t('analytics:empty.series')}
            height={240}
          >
            <TimeSeriesChart
              data={series}
              metrics={seriesMetrics}
              xTickFormatter={bucketFormatter}
              tooltipLabelFormatter={bucketFormatter}
              yTickFormatter={
                priceVisible
                  ? (v) => fmtCurrencyCompact(Number(v) || 0)
                  : (v) => fmtCreditsShort(v)
              }
            />
          </ChartCard>

          <Separator />

          <div className="flex items-center justify-between gap-2">
            <span id="usage-group-by-label" className="text-sm font-medium text-foreground">
              {t('usage.groupBy')}
            </span>
            <div
              role="group"
              aria-labelledby="usage-group-by-label"
              className="flex overflow-hidden rounded-lg border border-border"
            >
              {GROUP_BY_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setGroupBy(opt.value)}
                  aria-pressed={groupBy === opt.value}
                  className={cn(
                    'px-3 py-1.5 text-sm transition-colors',
                    groupBy === opt.value
                      ? 'bg-accent text-accent-foreground'
                      : 'bg-background text-foreground-secondary hover:bg-background-secondary',
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <ChartCard
            title={groupBy === 'model' ? t('analytics:chart.byModel') : t('analytics:chart.breakdown')}
            loading={isLoading}
            empty={breakdownRows.length === 0}
            emptyLabel={t('usage.noUsageYet')}
            height={Math.max(180, Math.min(breakdownRows.length, 8) * 40 + 40)}
          >
            <BreakdownBarChart
              data={breakdownRows}
              dataKey={breakdownKey}
              labelKey="label"
              metricLabel={priceVisible ? t('analytics:metrics.cost') : t('usage.credits')}
              valueFormatter={
                priceVisible
                  ? (v) => fmtCurrencyCompact(Number(v) || 0)
                  : (v) => fmtCreditsShort(v)
              }
            />
          </ChartCard>

          {top5.length > 0 && (
            <>
              <Separator />
              <div>
                <h3 className="mb-3 font-medium text-foreground">
                  {priceVisible ? t('usage.topByCost') : t('usage.topByCredits')}
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border">
                        <th className="px-3 py-2 text-start font-medium text-foreground-secondary">
                          {groupBy === 'model' ? t('usage.model') : t('usage.feature')}
                        </th>
                        <th className="px-3 py-2 text-end font-medium text-foreground-secondary">
                          {priceVisible ? t('usage.cost') : t('usage.credits')}
                        </th>
                        <th className="px-3 py-2 text-end font-medium text-foreground-secondary">
                          {t('usage.tokens')}
                        </th>
                        <th className="px-3 py-2 text-end font-medium text-foreground-secondary">
                          {t('usage.requests')}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {top5.map((row, i) => (
                        <tr
                          key={i}
                          className="border-b border-border/50 transition-colors hover:bg-background-secondary/50"
                        >
                          <td className="px-3 py-2 text-foreground">{labelFor(row.key)}</td>
                          <td className="px-3 py-2 text-end font-semibold text-foreground">
                            {priceVisible ? (
                              <CostValue usd={row.total_cost} />
                            ) : (
                              <CreditValue credits={row.credits} suffixKey="credits.jetonSuffix" />
                            )}
                          </td>
                          <td className="px-3 py-2 text-end text-foreground-secondary">
                            {fmtTokensShort(row.total_tokens)}
                          </td>
                          <td className="px-3 py-2 text-end text-foreground-secondary">
                            {fmtNumber(row.count ?? 0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}

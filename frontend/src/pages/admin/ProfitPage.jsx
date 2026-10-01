import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
  TrendingUp,
  DollarSign,
  Server,
  Wallet,
  Percent,
  ArrowRight,
  ChevronDown,
  Inbox,
  Loader2,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatTile } from '@/components/ui/StatTile'
import { ChartCard } from '@/components/charts/ChartCard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { GranularityRangePicker } from '@/components/charts/GranularityRangePicker'
import { CostValue } from '@/components/ui/CostValue'
import { fmtCurrency, fmtNumber } from '@/utils/persianLocale'
import { fmtDate } from '@/utils/dateLocale'
import { adminService } from '@/services/adminService'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import { cn } from '@/lib/utils'
import { ByModelCard } from './analytics/ByModelCard'
import { useAnalyticsControls } from './analytics/useAnalyticsControls'
import { deltaFraction } from './analytics/metrics'

/**
 * /admin/profit — the CEO profit dashboard. Reads the new
 * `GET /admin/analytics/profit` envelope (revenue = markup-priced spend, upstream
 * = raw OpenRouter cost, margin = revenue − upstream) and lays it out with the
 * shared analytics kit: 4 StatTiles, a three-series time-series (revenue /
 * upstream / margin share one $ Y axis), a by-company drilldown table, and a
 * by-model split.
 *
 * Margin is the sensitive figure here, not cost — admin-only, so `margin_visible`
 * is normally true, but we honour `false` (hide upstream + margin + margin%,
 * keep revenue) so the page degrades for any future non-finance admin.
 *
 * All money flows through CostValue / fmtCurrency; the chart tooltip escapes its
 * own values via the kit's `enc` helper (ChartTooltip), so nothing here is an
 * innerHTML sink.
 */
export default function ProfitPage() {
  const { t } = useTranslation('admin')
  const { t: ta } = useTranslation('analytics')
  const { range, onRangeChange } = useAnalyticsControls()

  const query = useQuery({
    queryKey: ['admin-profit', range.granularity, range.from, range.to],
    queryFn: () =>
      adminService.getProfit({
        from: range.from,
        to: range.to,
        granularity: range.granularity,
        breakdown: 'model',
      }),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
    placeholderData: (prev) => prev,
  })

  const data = query.data
  const marginVisible = data?.margin_visible !== false
  const series = data?.series || []
  const totals = data?.totals || {}
  const deltas = data?.deltas || {}
  const byCompany = data?.by_company || []
  const byModel = data?.by_model || []
  const win = data?.window || {}

  // Localized bucket label for axis + tooltip — Shamsi under fa, granularity-aware.
  const dateFmt = range.granularity === 'month' ? 'MMM yyyy' : 'd MMM'
  const xTickFormatter = useMemo(
    () => (v) => {
      if (!v) return ''
      const d = new Date(v)
      return Number.isNaN(d.getTime()) ? v : fmtDate(d, dateFmt)
    },
    [dateFmt],
  )

  // Three $-magnitude series on ONE Y axis. Colors are semantic: revenue = royal
  // (chart-1, the brand line), upstream cost = pink (chart-5, the outflow lane),
  // margin = green (chart-6, profit). Upstream + margin drop out when margin is
  // masked, leaving the revenue line alone.
  const seriesMetrics = useMemo(() => {
    const fmtMoney = (v) => fmtCurrency(Number(v) || 0)
    const list = [
      {
        key: 'revenue',
        label: ta('metrics.revenue', 'Revenue'),
        colorIndex: 1,
        formatter: fmtMoney,
      },
    ]
    if (marginVisible) {
      list.push(
        {
          key: 'upstream_cost',
          label: ta('metrics.upstreamCost', 'Upstream cost'),
          colorIndex: 5,
          formatter: fmtMoney,
        },
        {
          key: 'margin',
          label: ta('metrics.margin', 'Margin'),
          colorIndex: 6,
          formatter: fmtMoney,
        },
      )
    }
    return list
  }, [ta, marginVisible])

  const yTickFormatter = (v) => fmtCurrency(Number(v) || 0)

  // First load = spinner; range changes keep prior data mounted + dimmed.
  if (query.isLoading && !data) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
      </div>
    )
  }
  if (query.error && !data) {
    return (
      <div className="flex flex-col items-center gap-3 p-12 text-center">
        <p className="text-error">{query.error?.response?.data?.error || t('profit.loadError')}</p>
        <Button variant="outline" size="sm" onClick={() => query.refetch()}>
          {ta('error.retry', 'Retry')}
        </Button>
      </div>
    )
  }

  const refetching = query.isFetching && !!data
  const windowSubtitle =
    win.from && win.to ? ta('totals.window', { from: win.from, to: win.to }) : undefined

  // StatTile descriptors — revenue always, then the margin trio gated on
  // visibility. Sparklines read the matching series field.
  const marginPct = totals.margin_pct
  const tiles = [
    {
      key: 'revenue',
      icon: DollarSign,
      label: ta('metrics.revenue', 'Revenue'),
      value: <CostValue usd={totals.revenue} />,
      delta: deltaFraction(deltas.revenue?.pct),
      spark: series.map((p) => Number(p?.revenue) || 0),
      sparkColorIndex: 1,
    },
    marginVisible && {
      key: 'upstream_cost',
      icon: Server,
      label: ta('metrics.upstreamCost', 'Upstream cost'),
      value: <CostValue usd={totals.upstream_cost} />,
      delta: deltaFraction(deltas.upstream_cost?.pct),
      spark: series.map((p) => Number(p?.upstream_cost) || 0),
      sparkColorIndex: 5,
    },
    marginVisible && {
      key: 'margin',
      icon: Wallet,
      label: ta('metrics.margin', 'Margin'),
      value: <CostValue usd={totals.margin} />,
      tone: Number(totals.margin) < 0 ? 'negative' : 'positive',
      delta: deltaFraction(deltas.margin?.pct),
      spark: series.map((p) => Number(p?.margin) || 0),
      sparkColorIndex: 6,
    },
    marginVisible && {
      key: 'margin_pct',
      icon: Percent,
      label: t('profit.kpi.marginPct'),
      value:
        marginPct == null
          ? '—'
          : `${fmtNumber(Number(marginPct), { decimals: 1 })}%`,
      delta: deltaFraction(deltas.margin_pct?.pct),
      spark: series.map((p) => Number(p?.margin_pct) || 0),
      sparkColorIndex: 6,
    },
  ].filter(Boolean)

  return (
    <PageShell width="dense">
      <PageHeader
        icon={TrendingUp}
        tone="emerald"
        title={t('profit.title')}
        subtitle={t('profit.subtitle')}
        actions={
          <GranularityRangePicker
            value={range}
            onChange={onRangeChange}
            disabled={refetching}
          />
        }
      />

      <div
        className={cn(
          'space-y-6 transition-opacity duration-200',
          refetching && 'pointer-events-none animate-pulse opacity-60',
        )}
        aria-busy={refetching}
      >
        {/* KPI tiles */}
        <div
          className={cn(
            'grid grid-cols-2 gap-3',
            marginVisible ? 'lg:grid-cols-4' : 'lg:grid-cols-1',
          )}
        >
          {tiles.map((tile) => (
            <StatTile
              key={tile.key}
              icon={tile.icon}
              label={tile.label}
              value={tile.value}
              tone={tile.tone}
              delta={tile.delta}
              deltaDirection="neutral"
              spark={tile.spark}
              sparkColorIndex={tile.sparkColorIndex}
            />
          ))}
        </div>

        {/* Revenue / upstream / margin over time */}
        <ChartCard
          title={t('profit.chart.title')}
          subtitle={windowSubtitle}
          loading={query.isLoading && !data}
          empty={series.length === 0}
          emptyLabel={ta('empty.series', 'No usage in this period.')}
          height={320}
        >
          <TimeSeriesChart
            data={series}
            metrics={seriesMetrics}
            variant="area"
            xTickFormatter={xTickFormatter}
            yTickFormatter={yTickFormatter}
            tooltipLabelFormatter={xTickFormatter}
          />
        </ChartCard>

        {/* By-company profit table */}
        <Card>
          <CardContent className="p-0">
            <div className="border-b border-border px-4 py-3 text-sm font-semibold text-foreground">
              {t('profit.byCompany')}
            </div>
            <ProfitCompanyTable
              rows={byCompany}
              marginVisible={marginVisible}
            />
          </CardContent>
        </Card>

        {/* By-model margin split */}
        <ByModelCard
          byModel={byModel}
          loading={query.isLoading && !data}
          costVisible={marginVisible}
        />
      </div>
    </PageShell>
  )
}

/**
 * Rows are revealed in pages of this size to cap the rendered table — a holding
 * with hundreds of companies would otherwise paint every row at once.
 */
const ROW_PAGE = 20

/**
 * By-company profit breakdown: revenue / upstream cost / margin / margin% per
 * company, each row a keyboard-accessible link to the company analytics page.
 * Extends the ChildrenTable interaction pattern (button rows + Enter/Space) but
 * carries the profit-specific columns instead of the standard usage metrics.
 *
 * Upstream + margin + margin% columns drop out when margin is masked, leaving
 * revenue as the only money column.
 */
function ProfitCompanyTable({ rows, marginVisible }) {
  const { t } = useTranslation('admin')
  const { t: ta } = useTranslation('analytics')
  const navigate = useNavigate()
  const list = Array.isArray(rows) ? rows : []
  const [visibleCount, setVisibleCount] = useState(ROW_PAGE)

  if (list.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12 text-center text-foreground-tertiary">
        <span className="grid size-10 place-items-center rounded-full bg-background-tertiary">
          <Inbox className="h-4 w-4" aria-hidden />
        </span>
        <span className="text-sm">{ta('empty.breakdown', 'No breakdown data in this period.')}</span>
      </div>
    )
  }

  const visibleRows = list.slice(0, visibleCount)
  const remaining = list.length - visibleRows.length
  // name + revenue + open (3) + optional upstream/margin/margin%.
  const colSpan = 3 + (marginVisible ? 3 : 0)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-background-tertiary text-xs uppercase tracking-wide text-foreground-secondary">
          <tr>
            <th className="px-4 py-2.5 text-start font-bold">{ta('table.company', 'Company')}</th>
            <th className="px-4 py-2.5 text-end font-bold">{ta('table.revenue', 'Revenue')}</th>
            {marginVisible && (
              <>
                <th className="px-4 py-2.5 text-end font-bold">
                  {ta('metrics.upstreamCost', 'Upstream cost')}
                </th>
                <th className="px-4 py-2.5 text-end font-bold">{ta('table.margin', 'Margin')}</th>
                <th className="px-4 py-2.5 text-end font-bold">{ta('table.marginPct', 'Margin %')}</th>
              </>
            )}
            <th className="px-4 py-2.5 text-end font-bold sr-only">{ta('table.open', 'Open')}</th>
          </tr>
        </thead>
        <tbody>
          {visibleRows.map((c) => {
            const href = c.id ? `/admin/companies/${c.id}` : null
            const go = () => href && navigate(href)
            const mp = c.margin_pct
            const marginNeg = Number(c.margin) < 0
            return (
              <tr
                key={c.id || c.label}
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
                  <span className="truncate font-medium text-foreground">{c.label}</span>
                </td>
                <td className="px-4 py-2.5 text-end tabular-nums">
                  <CostValue usd={c.revenue} />
                </td>
                {marginVisible && (
                  <>
                    <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary">
                      <CostValue usd={c.upstream_cost} />
                    </td>
                    <td
                      className={cn(
                        'px-4 py-2.5 text-end tabular-nums font-medium',
                        marginNeg ? 'text-error' : 'text-success',
                      )}
                    >
                      <CostValue usd={c.margin} />
                    </td>
                    <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary">
                      {mp == null ? '—' : `${fmtNumber(Number(mp), { decimals: 1 })}%`}
                    </td>
                  </>
                )}
                <td className="px-4 py-2.5 text-end">
                  {href && (
                    <ArrowRight
                      className="ms-auto h-4 w-4 flex-shrink-0 text-foreground-tertiary rtl:rotate-180"
                      aria-hidden
                    />
                  )}
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
                  {ta('table.showMore', { count: Math.min(remaining, ROW_PAGE) })}
                </button>
              </td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  )
}

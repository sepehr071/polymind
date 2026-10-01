import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatTile } from '@/components/ui/StatTile'
import { ChartCard } from '@/components/charts/ChartCard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { BreakdownBarChart } from '@/components/charts/BreakdownBarChart'
import { ExportButton } from '@/components/charts/ExportButton'
import { GranularityRangePicker } from '@/components/charts/GranularityRangePicker'
import { CostValue } from '@/components/ui/CostValue'
import { fmtNumber, fmtCurrency } from '@/utils/persianLocale'
import { fmtDate } from '@/utils/dateLocale'
import { prettifyModelName } from '@/utils/modelName'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import { MetricToggle } from './MetricToggle'
import { ChildrenTable } from './ChildrenTable'
import { METRICS, METRIC_BY_KEY, deltaFraction } from './metrics'

/**
 * The shared body for every admin analytics dashboard (overview, company, team,
 * user). Owns the standard composition so each page stays a thin descriptor:
 *
 *   header (passed in) → GranularityRangePicker + ExportButton
 *   → StatTile row (4 metrics, deltas + sparklines)
 *   → TimeSeriesChart with a metric toggle
 *   → BreakdownBarChart of children (or by_model for the user leaf)
 *   → ChildrenTable (clickable drilldown) — omitted for the user leaf
 *
 * All cost goes through CostValue/fmtCurrency; all counts through fmtNumber;
 * dates through fmtDate (Shamsi under fa). Cost surfaces auto-mask off
 * `data.cost_visible`.
 *
 * Header is a canonical <PageHeader> rendered internally — pages pass a
 * structured descriptor (title/icon/tone/backTo/backLabel) instead of raw JSX.
 * The GranularityRangePicker + ExportButton live in the header's actions slot,
 * alongside any page-specific `headerActions` (e.g. a credit-transfer button).
 * The legacy `header` JSX prop is still accepted as a fallback for callers that
 * haven't migrated.
 *
 * @param {object} props
 * @param {React.ReactNode} [props.title]       page title (descriptor form)
 * @param {React.ElementType} [props.icon]      lucide icon for the tinted IconTile
 * @param {string} [props.tone]                 IconTile tone (default 'sky')
 * @param {string} [props.subtitle]             one-line description under the title
 * @param {string} [props.backTo]               react-router path for the back link
 * @param {React.ReactNode} [props.backLabel]   back link text
 * @param {React.ReactNode} [props.headerActions]  page-specific end-side controls (rendered before the range picker)
 * @param {React.ReactNode} [props.header]      DEPRECATED raw header JSX (back-compat)
 * @param {object} props.data                   the analytics envelope (or undefined while loading)
 * @param {boolean} props.isLoading
 * @param {boolean} props.isFetching            background refetch (dims, keeps prior data)
 * @param {Error}  props.error
 * @param {() => void} props.onRetry
 * @param {{granularity,from,to}} props.range
 * @param {(next)=>void} props.onRangeChange
 * @param {string} props.metric                 active time-series metric key
 * @param {(key)=>void} props.onMetricChange
 * @param {string} props.breakdownTitle         title for the breakdown card
 * @param {string} props.childNameLabel         entity-column header in the table (e.g. "Company")
 * @param {(child)=>string} [props.rowHref]     row → route; omit for the user leaf
 * @param {boolean} [props.showActiveUsers]     active-users column in the table (default true)
 * @param {'children'|'by_model'} [props.breakdownSource]  which list feeds the bar/table (default 'children')
 * @param {React.ReactNode} [props.footer]      extra composed sections rendered below the
 *                                              breakdown, inside the same refetch-dim container
 *                                              (e.g. holding's by-model + credits + CEO). Omit for
 *                                              the standard drilldown pages.
 */
export function AnalyticsScaffold({
  header,
  title,
  icon,
  tone = 'sky',
  subtitle,
  backTo,
  backLabel,
  headerActions,
  data,
  isLoading,
  isFetching,
  error,
  onRetry,
  range,
  onRangeChange,
  metric,
  onMetricChange,
  breakdownTitle,
  childNameLabel,
  rowHref,
  showActiveUsers = true,
  breakdownSource = 'children',
  footer,
}) {
  const { t } = useTranslation('analytics')

  const costVisible = data?.cost_visible !== false
  const series = data?.series || []
  const totals = data?.totals || {}
  const deltas = data?.deltas || {}
  const children = data?.breakdown?.children || []
  const byModel = data?.breakdown?.by_model || []
  // Humanize model labels from the raw slug `key` for the bar chart; children
  // (company/team/user names) stay verbatim.
  const breakdownRows =
    breakdownSource === 'by_model'
      ? byModel.map((m) => ({ ...m, label: prettifyModelName(m.key) || m.label }))
      : children
  const win = data?.window || {}

  // Resolve the plotted metric SYNCHRONOUSLY: if the selected metric is
  // cost-sensitive but cost is masked, fall back to calls for this render so a
  // masked viewer never gets an all-null first paint (the parent effect that
  // re-syncs the toggle state would otherwise only correct it next render).
  let activeMetric = METRIC_BY_KEY[metric] || METRIC_BY_KEY.cost
  if (!costVisible && activeMetric.costSensitive) {
    activeMetric = METRIC_BY_KEY.calls
  }

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

  const seriesMetrics = useMemo(
    () => [
      {
        key: activeMetric.key,
        label: t(`metrics.${activeMetric.i18nKey}`),
        colorIndex: activeMetric.colorIndex,
        formatter: activeMetric.format,
      },
    ],
    [activeMetric, t],
  )

  // First load = full spinner; subsequent range/scope changes keep prior data
  // mounted and dim it (the established HoldingOverview pattern).
  if (isLoading && !data) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
      </div>
    )
  }
  if (error && !data) {
    return (
      <div className="flex flex-col items-center gap-3 p-12 text-center">
        <p className="text-error">{error?.response?.data?.error || t('error.load')}</p>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            {t('error.retry')}
          </Button>
        )}
      </div>
    )
  }

  const refetching = isFetching && !!data
  const windowSubtitle =
    win.from && win.to ? t('totals.window', { from: win.from, to: win.to }) : undefined

  const yTickFormatter = (v) =>
    activeMetric.key === 'cost' ? fmtCurrency(Number(v) || 0) : fmtNumber(Number(v) || 0)

  const toolbar = (
    <>
      {headerActions}
      <GranularityRangePicker value={range} onChange={onRangeChange} disabled={refetching} />
      <ExportButton envelope={data} scope={data?.scope} />
    </>
  )

  return (
    <PageShell width="dense">
        {/* Header + toolbar — canonical PageHeader with the range/export controls
            (plus any page-specific actions) in the actions slot. Falls back to the
            legacy raw `header` JSX when no `title` descriptor is supplied. */}
        {title != null ? (
          <PageHeader
            icon={icon}
            tone={tone}
            title={title}
            subtitle={subtitle}
            backTo={backTo}
            backLabel={backLabel}
            actions={toolbar}
          />
        ) : (
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">{header}</div>
            <div className="flex flex-wrap items-center gap-2">{toolbar}</div>
          </div>
        )}

        <div
          className={`space-y-6 transition-opacity duration-200 ${
            refetching ? 'pointer-events-none animate-pulse opacity-60' : ''
          }`}
          aria-busy={refetching}
        >
          {/* Stat tiles */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {METRICS.filter((m) => costVisible || !m.costSensitive).map((m) => {
              const sparkData = series.map((p) => Number(p?.[m.key]) || 0)
              const value =
                m.key === 'cost' && !costVisible ? t('costHidden') : m.format(totals[m.key])
              return (
                <StatTile
                  key={m.key}
                  icon={m.icon}
                  label={t(`metrics.${m.i18nKey}`)}
                  value={value}
                  delta={deltaFraction(deltas[m.key]?.pct)}
                  deltaDirection={m.deltaDirection}
                  spark={sparkData}
                  sparkColorIndex={m.colorIndex}
                />
              )
            })}
          </div>

          {/* Series + breakdown side-by-side on wide screens (12-col grid):
              the usage-over-time line takes the wider 7-col lane, the breakdown
              (top-N bar + drilldown/model table) the narrower 5-col lane. Stacks
              vertically below xl. */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            {/* Time series */}
            <ChartCard
              className="xl:col-span-7"
              title={t('chart.usageOverTime')}
              subtitle={windowSubtitle}
              toolbar={
                <MetricToggle value={metric} onChange={onMetricChange} costVisible={costVisible} />
              }
              loading={isLoading && !data}
              empty={series.length === 0}
              emptyLabel={t('empty.series')}
              height={300}
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

            {/* Breakdown bar (top-N) + drilldown / model table */}
            <div className="space-y-4 xl:col-span-5">
              <ChartCard
                title={t('chart.topN', { count: 8 })}
                subtitle={breakdownTitle}
                loading={isLoading && !data}
                empty={breakdownRows.length === 0}
                emptyLabel={t('empty.breakdown')}
                height={332}
              >
                <BreakdownBarChart
                  data={breakdownRows}
                  dataKey={costVisible ? 'cost' : 'calls'}
                  labelKey="label"
                  topN={8}
                  metricLabel={costVisible ? t('metrics.cost') : t('metrics.calls')}
                  valueFormatter={costVisible ? activeMetricCostFmt : fmtNumberFmt}
                />
              </ChartCard>

              <Card>
                <CardContent className="p-0">
                  <div className="border-b border-border px-4 py-3 text-sm font-semibold text-foreground">
                    {breakdownTitle}
                  </div>
                  {breakdownSource === 'by_model' ? (
                    <ModelTable rows={byModel} costVisible={costVisible} />
                  ) : (
                    <ChildrenTable
                      children={children}
                      rowHref={rowHref}
                      nameLabel={childNameLabel}
                      costVisible={costVisible}
                      showActiveUsers={showActiveUsers}
                    />
                  )}
                </CardContent>
              </Card>
            </div>
          </div>

          {footer}
        </div>
    </PageShell>
  )
}

const activeMetricCostFmt = (v) => fmtCurrency(Number(v) || 0)
const fmtNumberFmt = (v) => fmtNumber(Number(v) || 0)

/** Model breakdown table for the user-leaf scope (no drilldown, friendly model names). */
function ModelTable({ rows, costVisible }) {
  const { t } = useTranslation('analytics')
  const list = Array.isArray(rows) ? rows : []
  if (list.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-foreground-tertiary">{t('empty.models')}</div>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-background-tertiary text-xs uppercase tracking-wide text-foreground-secondary">
          <tr>
            <th className="px-4 py-2.5 text-start font-bold">{t('table.model')}</th>
            {costVisible && (
              <th className="px-4 py-2.5 text-end font-bold">{t('table.cost')}</th>
            )}
            <th className="px-4 py-2.5 text-end font-bold">{t('table.calls')}</th>
            <th className="px-4 py-2.5 text-end font-bold">{t('table.tokens')}</th>
          </tr>
        </thead>
        <tbody>
          {list.map((m) => (
            <tr key={m.key} className="border-t border-border">
              <td className="px-4 py-2.5">
                <div className="font-medium text-foreground">{prettifyModelName(m.key) || m.label}</div>
              </td>
              {costVisible && (
                <td className="px-4 py-2.5 text-end tabular-nums">
                  <CostValue usd={m.cost} />
                </td>
              )}
              <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary">
                {fmtNumber(m.calls)}
              </td>
              <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary">
                {fmtNumber(m.tokens)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default AnalyticsScaffold

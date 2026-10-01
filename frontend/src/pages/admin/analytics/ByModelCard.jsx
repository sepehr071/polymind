import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ChartCard } from '@/components/charts/ChartCard'
import { SharePie } from '@/components/charts/SharePie'
import { BreakdownBarChart } from '@/components/charts/BreakdownBarChart'
import { fmtNumber, fmtCurrency } from '@/utils/persianLocale'
import { prettifyModelName } from '@/utils/modelName'

const fmtCost = (v) => fmtCurrency(Number(v) || 0)
const fmtCount = (v) => fmtNumber(Number(v) || 0)

/**
 * Model-split breakdown for an analytics envelope (`breakdown.by_model`): a share
 * donut beside the ranked top-N bars. Companion to AnalyticsScaffold for scopes
 * whose primary breakdown is children (companies/teams) but that ALSO want a
 * model split below — e.g. the holding overview, where the children table covers
 * companies and this covers models.
 *
 * Reuses the Kit-B conventions: ChartCard async shell, `prettifyModelName` on the
 * raw slug `key`, cost-when-visible-else-calls ranking, tooltip values escaped by
 * the shared chart-kit `enc` helper inside SharePie/BreakdownBarChart.
 *
 * @param {Array<object>} byModel       envelope `breakdown.by_model`
 * @param {boolean} [loading]
 * @param {boolean} [costVisible]
 */
export function ByModelCard({ byModel, loading = false, costVisible = true }) {
  const { t } = useTranslation('analytics')

  // Humanize the raw provider-prefixed slug `key` once; feeds pie + bars + their
  // tooltips through the shared `labelKey="label"`.
  const rows = useMemo(
    () =>
      (Array.isArray(byModel) ? byModel : []).map((m) => ({
        ...m,
        label: prettifyModelName(m.key) || m.label,
      })),
    [byModel],
  )

  // Rank by cost when visible, else by calls, so the split is meaningful even
  // when $ is masked (it isn't on the admin tier — keep it correct regardless).
  const metricKey = costVisible ? 'cost' : 'calls'
  const formatter = costVisible ? fmtCost : fmtCount
  const empty = rows.length === 0

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <ChartCard
        title={t('chart.byModel')}
        subtitle={t('chart.share')}
        loading={loading}
        empty={empty}
        emptyLabel={t('empty.models')}
        height={300}
      >
        <SharePie data={rows} dataKey={metricKey} valueFormatter={formatter} />
      </ChartCard>

      <ChartCard
        title={t('chart.byModel')}
        subtitle={t('chart.topN', { count: 8 })}
        loading={loading}
        empty={empty}
        emptyLabel={t('empty.models')}
        height={300}
      >
        <BreakdownBarChart
          data={rows}
          dataKey={metricKey}
          labelKey="label"
          topN={8}
          valueFormatter={formatter}
          metricLabel={costVisible ? t('metrics.cost') : t('metrics.calls')}
        />
      </ChartCard>
    </div>
  )
}

export default ByModelCard

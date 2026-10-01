import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { UserCircle } from 'lucide-react'
import { useAnalytics } from '@/hooks/useAnalytics'
import { AnalyticsScaffold } from './analytics/AnalyticsScaffold'
import { useAnalyticsControls } from './analytics/useAnalyticsControls'

/**
 * /admin/companies/:wid/teams/:pid/users/:uid — user-scoped analytics
 * (scope=user, leaf). No children; the breakdown is the per-model split
 * (`breakdown.by_model`).
 */
export default function UserDetailPage() {
  const { wid, pid, uid } = useParams()
  const { t } = useTranslation('analytics')
  const { range, onRangeChange, metric, setMetric } = useAnalyticsControls()

  const query = useAnalytics({
    tier: 'admin',
    scope: 'user',
    id: uid,
    granularity: range.granularity,
    from: range.from,
    to: range.to,
    breakdown: 'model',
  })

  return (
    <AnalyticsScaffold
      icon={UserCircle}
      tone="sky"
      title={t('title.user')}
      subtitle={t('subtitle.user')}
      backTo={`/admin/companies/${wid}/teams/${pid}`}
      backLabel={t('back.team')}
      data={query.data}
      isLoading={query.isLoading}
      isFetching={query.isFetching}
      error={query.error}
      onRetry={query.refetch}
      range={range}
      onRangeChange={onRangeChange}
      metric={metric}
      onMetricChange={setMetric}
      breakdownTitle={t('chart.byModel')}
      childNameLabel={t('table.model')}
      breakdownSource="by_model"
    />
  )
}

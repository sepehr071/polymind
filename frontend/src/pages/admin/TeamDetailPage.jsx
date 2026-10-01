import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Users } from 'lucide-react'
import { useAnalytics } from '@/hooks/useAnalytics'
import { AnalyticsScaffold } from './analytics/AnalyticsScaffold'
import { useAnalyticsControls } from './analytics/useAnalyticsControls'

/**
 * /admin/companies/:wid/teams/:pid — team-scoped analytics (scope=team).
 * Children are the team's users; each row drills into the user detail. The
 * per-user active-users column is dropped (it's always 1 per row).
 */
export default function TeamDetailPage() {
  const { wid, pid } = useParams()
  const { t } = useTranslation('analytics')
  const { range, onRangeChange, metric, setMetric } = useAnalyticsControls()

  const query = useAnalytics({
    tier: 'admin',
    scope: 'team',
    id: pid,
    granularity: range.granularity,
    from: range.from,
    to: range.to,
  })

  return (
    <AnalyticsScaffold
      icon={Users}
      tone="sky"
      title={t('title.team')}
      subtitle={t('subtitle.team')}
      backTo={`/admin/companies/${wid}`}
      backLabel={t('back.company')}
      data={query.data}
      isLoading={query.isLoading}
      isFetching={query.isFetching}
      error={query.error}
      onRetry={query.refetch}
      range={range}
      onRangeChange={onRangeChange}
      metric={metric}
      onMetricChange={setMetric}
      breakdownTitle={t('chart.byUser')}
      childNameLabel={t('table.user')}
      rowHref={(c) => `/admin/companies/${wid}/teams/${pid}/users/${c.id}`}
      showActiveUsers={false}
    />
  )
}

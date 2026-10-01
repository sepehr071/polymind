import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { ExternalLink, Building2, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { fmtCurrency } from '@/utils/persianLocale'
import { adminService } from '@/services/adminService'
import { useAnalytics } from '@/hooks/useAnalytics'
import AddCreditsDialog from '@/components/billing/AddCreditsDialog'
import { AnalyticsScaffold } from './analytics/AnalyticsScaffold'
import { useAnalyticsControls } from './analytics/useAnalyticsControls'

/**
 * /admin/companies/:wid — company-scoped analytics (scope=company). Children are
 * teams (projects); each row drills into the team detail. Migrated off the old
 * raw-useEffect fetch onto useAnalytics.
 *
 * Also hosts the holding→company credit transfer: the shared AddCreditsDialog in
 * `company` scope exposes a funding-source toggle (holding pool vs. external
 * top-up); the POST goes through `adminService.addCompanyCredits` (absorbed from
 * the retired /platform company-detail page).
 */
export default function CompanyDetailPage() {
  const { wid } = useParams()
  const { t } = useTranslation('analytics')
  const { t: tp } = useTranslation('admin')
  const { range, onRangeChange, metric, setMetric } = useAnalyticsControls()
  const [addOpen, setAddOpen] = useState(false)

  const query = useAnalytics({
    tier: 'admin',
    scope: 'company',
    id: wid,
    granularity: range.granularity,
    from: range.from,
    to: range.to,
  })

  const headerActions = (
    <>
      <Button variant="outline" size="sm" asChild>
        <Link to={`/workspaces/${wid}`}>
          <ExternalLink className="h-3.5 w-3.5" />
          {t('table.open')}
        </Link>
      </Button>
      <Button size="sm" onClick={() => setAddOpen(true)}>
        <Plus className="h-3.5 w-3.5" />
        {tp('companyDetail.addBtn', 'Add credits')}
      </Button>
    </>
  )

  return (
    <>
      <AnalyticsScaffold
        icon={Building2}
        tone="sky"
        title={t('title.company')}
        subtitle={t('subtitle.company')}
        backTo="/admin/companies"
        backLabel={t('back.overview')}
        headerActions={headerActions}
        data={query.data}
        isLoading={query.isLoading}
        isFetching={query.isFetching}
        error={query.error}
        onRetry={query.refetch}
        range={range}
        onRangeChange={onRangeChange}
        metric={metric}
        onMetricChange={setMetric}
        breakdownTitle={t('chart.byTeam')}
        childNameLabel={t('table.team')}
        rowHref={(c) => `/admin/companies/${wid}/teams/${c.id}`}
      />

      <AddCreditsDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        scope="company"
        onConfirm={async ({ amount, type, note, source }) => {
          const res = await adminService.addCompanyCredits(wid, {
            amountUsd: amount,
            type,
            note,
            source,
          })
          toast.success(
            tp('addCredits.companySuccess', 'Company charged — new balance {{value}}', {
              value: fmtCurrency(res?.credits_balance_usd || 0),
            }),
          )
          query.refetch()
        }}
      />
    </>
  )
}

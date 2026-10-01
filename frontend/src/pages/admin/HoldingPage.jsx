import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Building2, UserCircle, Wallet, Plus, Layers } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import { fmtCurrency } from '@/utils/persianLocale'
import { adminService } from '@/services/adminService'
import { useAnalytics } from '@/hooks/useAnalytics'
import AddCreditsDialog from '@/components/billing/AddCreditsDialog'
import { AnalyticsScaffold } from './analytics/AnalyticsScaffold'
import { ByModelCard } from './analytics/ByModelCard'
import { useAnalyticsControls } from './analytics/useAnalyticsControls'

/**
 * /admin/holding — the SINGLE deep-analytics workspace for the super-admin (the
 * old duplicate /platform chart kit was retired). Composes the shared Kit-B
 * AnalyticsScaffold at `scope='holding'` for the core (4 KPI tiles + usage-over-
 * time + by-company breakdown with drilldown + CSV), then layers the holding-only
 * sections — a by-model split, the credits wallet, and the CEO card — into the
 * scaffold's `footer` slot so they share its refetch-dim container.
 *
 * Two data sources: the unified `useAnalytics` envelope (usage) and the legacy
 * `adminService.getHoldingOverview` (billing + CEO — the envelope carries no
 * wallet). Also hosts the holding top-up via AddCreditsDialog at `holding` scope.
 */
export default function HoldingPage() {
  const { t } = useTranslation('admin')
  const { t: ta } = useTranslation('analytics')
  const { range, onRangeChange, metric, setMetric } = useAnalyticsControls()
  const [addOpen, setAddOpen] = useState(false)

  const query = useAnalytics({
    tier: 'admin',
    scope: 'holding',
    granularity: range.granularity,
    from: range.from,
    to: range.to,
    breakdown: 'model',
  })

  // Credits + CEO summary (legacy holding-overview endpoint — the analytics
  // envelope carries no billing). Kept on its own react-query key.
  const creditsQuery = useQuery({
    queryKey: ['admin-holding-credits'],
    queryFn: () => adminService.getHoldingOverview(30),
    staleTime: 60_000,
  })

  const costVisible = query.data?.cost_visible !== false
  const byModel = query.data?.breakdown?.by_model

  const summary = creditsQuery.data
  const ceo = summary?.ceo || null
  const credits = summary?.holding_credits || {}
  const remaining = Number(credits.remaining_usd || 0)
  const remainingClass =
    remaining < 0 ? 'text-error' : remaining < 100 ? 'text-foreground' : 'text-success'

  const reload = () => {
    creditsQuery.refetch()
    query.refetch()
  }

  const headerActions = (
    <>
      <span className="inline-flex items-center gap-1.5 rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1 text-[11px] font-semibold text-accent">
        <Layers className="h-3.5 w-3.5 flex-shrink-0" aria-hidden />
        <span>{t('scopeBanner.label')}</span>
      </span>
      <Button size="sm" onClick={() => setAddOpen(true)}>
        <Plus className="h-3.5 w-3.5" />
        {t('holding.chargeBtn')}
      </Button>
    </>
  )

  // Holding-only sections, rendered inside the scaffold's refetch-dim container.
  // Grouped to stay scannable: model split first, then credits + CEO share a row.
  const footer = (
    <div className="space-y-6 pt-2">
      <ByModelCard byModel={byModel} loading={query.isLoading && !query.data} costVisible={costVisible} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Holding credits wallet */}
        <Card>
          <CardContent className="flex h-full flex-col p-5">
            <div className="mb-4 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Wallet className="h-4 w-4" aria-hidden />
                {t('holding.credits.title')}
              </div>
              <Button size="sm" variant="outline" className="h-7" onClick={() => setAddOpen(true)}>
                <Plus className="h-3.5 w-3.5" />
                {t('holding.chargeBtn')}
              </Button>
            </div>
            {/* Flat stat-tiles (stat-tile spec: surf2, 1px line, radius14, label
                12/fg3, value 24/800). Rendered as flat divs — not the Card-based
                ui/StatTile — to avoid nesting a card inside this wallet Card. */}
            <dl className="grid flex-1 grid-cols-3 gap-3">
              <WalletStat
                label={t('holding.credits.lifetimeTopups')}
                value={fmtCurrency(credits.lifetime_topups_usd)}
              />
              <WalletStat
                label={t('holding.credits.lifetimeSpend')}
                value={fmtCurrency(credits.lifetime_spend_usd)}
              />
              <WalletStat
                label={t('holding.credits.remaining')}
                value={fmtCurrency(credits.remaining_usd)}
                valueClassName={remainingClass}
              />
            </dl>
          </CardContent>
        </Card>

        {/* CEO card */}
        <Card>
          <CardContent className="flex h-full flex-col p-5">
            <div className="flex items-start gap-3">
              <IconTile icon={UserCircle} tone="sky" size="xl" />
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-foreground">{t('holding.ceo.title')}</h2>
                <p className="mt-0.5 text-xs text-foreground-tertiary">{t('holding.ceo.subtitle')}</p>
              </div>
            </div>
            {ceo ? (
              <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                <div className="space-y-0.5">
                  <dt className="text-xs uppercase tracking-wide text-foreground-tertiary">
                    {t('holding.ceo.email')}
                  </dt>
                  <dd className="truncate text-foreground" dir="ltr">
                    {ceo.email || '—'}
                  </dd>
                </div>
                <div className="space-y-0.5">
                  <dt className="text-xs uppercase tracking-wide text-foreground-tertiary">
                    {t('holding.ceo.displayName')}
                  </dt>
                  <dd className="truncate text-foreground">
                    {ceo.display_name || ceo.profile?.display_name || '—'}
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="mt-4 text-sm text-foreground-secondary">{t('holding.ceo.noCEO')}</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )

  return (
    <>
      <AnalyticsScaffold
        icon={Building2}
        tone="sky"
        title={t('holding.title')}
        subtitle={t('holding.subtitle')}
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
        breakdownTitle={ta('chart.byCompany', 'By company')}
        childNameLabel={ta('table.company', 'Company')}
        rowHref={(c) => `/admin/companies/${c.id}`}
        footer={footer}
      />

      <AddCreditsDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        scope="holding"
        onConfirm={async ({ amount, type, note }) => {
          const res = await adminService.addHoldingCredits({
            amountUsd: amount,
            type,
            note,
          })
          toast.success(
            t('addCredits.holdingSuccess', 'Organization topped up — lifetime {{value}}', {
              value: fmtCurrency(res?.lifetime_topups_usd || 0),
            }),
          )
          reload()
        }}
      />
    </>
  )
}

/** Nested stat-tile (stat-tile spec) for the credits wallet — a div, not a Card,
 *  so it doesn't nest a card inside the wallet Card. Sits INSIDE the already-glass
 *  wallet Card → nested tier (semi-transparent surf, no 2nd glass layer). */
function WalletStat({ label, value, valueClassName }) {
  return (
    <div className="rounded-xl border border-line bg-bg-2/50 p-3">
      <dt className="text-[12px] font-medium text-foreground-tertiary">{label}</dt>
      <dd
        className={`mt-1.5 text-2xl font-extrabold leading-tight tracking-[-0.01em] tabular-nums text-foreground ${valueClassName || ''}`}
      >
        {value}
      </dd>
    </div>
  )
}

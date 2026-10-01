import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import {
  Building2,
  Users,
  CircleDollarSign,
  TrendingUp,
  Wallet,
} from 'lucide-react'
import { useAnalytics } from '@/hooks/useAnalytics'
import { adminService } from '@/services/adminService'
import { CostValue } from '@/components/ui/CostValue'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { fmtNumber } from '@/utils/persianLocale'
import { fmtDate, fmtDistanceToNowSafe } from '@/utils/dateLocale'
import { getInitials } from '@/utils/avatarColor'
import PageShell from '@/components/layout/PageShell'

function isoDaysAgo(daysAgo) {
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function moneyTone(n) {
  const v = Number(n)
  if (!Number.isFinite(v)) return ''
  return v < 0 ? 'font-bold text-error' : 'font-bold text-success'
}

const KPIS = [
  { key: 'companies', icon: Building2, labelKey: 'overview.kpi.companies' },
  { key: 'members', icon: Users, labelKey: 'overview.kpi.activeMembers' },
  { key: 'cost', icon: CircleDollarSign, labelKey: 'overview.kpi.cost30' },
  { key: 'margin', icon: TrendingUp, labelKey: 'overview.kpi.margin' },
  { key: 'credit', icon: Wallet, labelKey: 'overview.kpi.credit' },
]

export default function AdminDashboard() {
  const { t } = useTranslation('admin')
  const range = useMemo(() => ({ from: isoDaysAgo(29), to: isoDaysAgo(0) }), [])

  const companiesQ = useQuery({
    queryKey: ['admin-companies', 30],
    queryFn: () => adminService.listCompanies(30),
    staleTime: 60_000,
  })
  const profitQ = useQuery({
    queryKey: ['admin-profit', 'day', range.from, range.to, 'none'],
    queryFn: () => adminService.getProfit({ from: range.from, to: range.to, granularity: 'day' }),
    staleTime: 60_000,
  })
  const pricingQ = useQuery({
    queryKey: ['admin-pricing'],
    queryFn: () => adminService.getPricing(),
    staleTime: 60_000,
  })
  const safetyQ = useQuery({
    queryKey: ['admin-dlp-summary', 30],
    queryFn: () => adminService.getDlpSummary(30),
    staleTime: 60_000,
  })
  const analytics = useAnalytics({
    tier: 'admin',
    scope: 'holding',
    granularity: 'day',
    from: range.from,
    to: range.to,
  })

  const companies = companiesQ.data?.companies || []
  const totals = companiesQ.data?.totals || {}
  const profit = profitQ.data?.totals || {}
  const marginVisible = profitQ.data?.margin_visible !== false
  const series = Array.isArray(profitQ.data?.series) ? profitQ.data.series : []
  const days = series.slice(-7)
  const dayMax = Math.max(1, ...days.map((p) => Number(marginVisible ? p.upstream_cost : p.revenue) || 0))
  const pricing = pricingQ.data || {}
  const markupPct = pricing.markup_pct == null ? null : Math.round(Number(pricing.markup_pct) * 1e6) / 1e4
  const safety = safetyQ.data || {}
  const topRules = (safety.top_rules || []).slice(0, 2).map((r) => r.rule_id).filter(Boolean)
  const negative = companies.filter((c) => Number(c.credits_balance_usd) < 0)
  const rows = [...companies].sort((a, b) => Number(a.credits_balance_usd || 0) - Number(b.credits_balance_usd || 0)).slice(0, 8)
  const loading = companiesQ.isLoading || profitQ.isLoading || analytics.isLoading

  const costUsd = marginVisible ? profit.upstream_cost : profit.revenue
  const values = {
    companies: fmtNumber(totals.companies ?? companies.length),
    members: fmtNumber(analytics.data?.totals?.active_users ?? 0),
    cost: <CostValue usd={costUsd} />,
    margin: marginVisible ? <CostValue usd={profit.margin} className={moneyTone(profit.margin)} /> : '—',
    credit: <CostValue usd={totals.credits_balance_usd} className={moneyTone(totals.credits_balance_usd)} />,
  }

  return (
    <PageShell width="full" className="space-y-3">
      <section className="grid grid-cols-2 gap-2 lg:grid-cols-5">
        {KPIS.map((kpi) => (
          <Card key={kpi.key}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between text-xs text-foreground-tertiary">
                <span>{t(kpi.labelKey)}</span>
                <kpi.icon className="h-3.5 w-3.5" />
              </div>
              <div className="mt-2 text-2xl font-extrabold tabular-nums">
                {loading ? <Skeleton className="h-8 w-24" /> : values[kpi.key]}
              </div>
            </CardContent>
          </Card>
        ))}
      </section>

      <section className="grid gap-3 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardContent className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-bold">{t('overview.companyCredits')}</h2>
              <Link to="/admin/companies" className="text-xs font-medium text-accent hover:underline">
                {t('overview.seeAll')}
              </Link>
            </div>
            {companiesQ.isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
              </div>
            ) : rows.length === 0 ? (
              <p className="py-6 text-center text-sm text-foreground-tertiary">{t('overview.noCompanies')}</p>
            ) : (
              <ul className="space-y-1">
                {rows.map((c) => (
                  <li key={c._id}>
                    <Link
                      to={`/admin/companies/${c._id}`}
                      className="flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-background-tertiary/60"
                    >
                      <Avatar size="sm" shape="square">
                        <AvatarFallback seed={c.name}>{getInitials(c.name)}</AvatarFallback>
                      </Avatar>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">{c.name}</span>
                        <span className="text-[11px] text-foreground-tertiary">
                          {t('overview.memberLine', {
                            count: fmtNumber(c.member_count || 0),
                            plan: t(`overview.plan.${String(c.plan_tier || 'free').toLowerCase()}`, {
                              defaultValue: c.plan_tier || t('overview.plan.free'),
                            }),
                          })}
                        </span>
                      </span>
                      <CostValue usd={c.usage_30d?.cost_usd} className="text-[11px] text-foreground-tertiary" />
                      <CostValue usd={c.credits_balance_usd} className={moneyTone(c.credits_balance_usd)} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            {negative.length > 0 && (
              <p className="mt-3 rounded-xl bg-error/10 px-3 py-2 text-xs text-error">
                {t('overview.negativeCompanies', { count: fmtNumber(negative.length) })}
              </p>
            )}
          </CardContent>
        </Card>

        <div className="space-y-3">
          <Card>
            <CardContent className="p-4">
              <h2 className="text-sm font-bold">{t('overview.profitTitle')}</h2>
              <dl className="mt-3 space-y-2 text-xs">
                <Row label={t('overview.markup')} value={markupPct == null ? '—' : `${fmtNumber(markupPct)}%`} />
                <Row label={t('overview.creditsPerUsd')} value={pricing.credits_per_usd == null ? '—' : fmtNumber(pricing.credits_per_usd)} />
                <Row label={t('overview.estimatedInvoice')} value={<CostValue usd={profit.revenue} />} />
              </dl>
              <Button variant="outline" size="sm" className="mt-3 w-full" asChild>
                <Link to="/admin/pricing">{t('overview.openPricing')}</Link>
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <h2 className="text-sm font-bold">{t('overview.spend7')}</h2>
              {days.length === 0 ? (
                <p className="mt-4 text-center text-xs text-foreground-tertiary">{t('overview.spendTrendEmpty')}</p>
              ) : (
                <>
                  <div className="mt-3 flex h-16 items-end gap-1">
                    {days.map((p) => {
                      const v = Number(marginVisible ? p.upstream_cost : p.revenue) || 0
                      return (
                        <div
                          key={p.bucket || p.date || p.day}
                          className="flex-1 rounded-t bg-accent/80"
                          style={{ height: `${Math.max(4, Math.round((v / dayMax) * 100))}%` }}
                          title={p.bucket || p.date || ''}
                        />
                      )
                    })}
                  </div>
                  <div className="mt-1 flex justify-between text-[10px] text-foreground-tertiary">
                    <span>{dayLabel(days[0])}</span>
                    <span>{dayLabel(days[days.length - 1])}</span>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardContent className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-bold">{t('overview.safetyTitle')}</h2>
              <Link to="/admin/dlp" className="text-xs font-medium text-accent hover:underline">
                {t('overview.safetyReport')}
              </Link>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <Mini label={t('overview.events')} value={safetyQ.isLoading ? '—' : fmtNumber(safety.total ?? 0)} />
              <Mini label={t('overview.confirms')} value={safetyQ.isLoading ? '—' : fmtNumber(safety.by_action?.require_confirm ?? 0)} className="text-warning" />
              <Mini label={t('overview.blocked')} value={safetyQ.isLoading ? '—' : fmtNumber(safety.by_action?.block ?? 0)} />
            </div>
            {topRules.length > 0 && (
              <p className="mt-3 text-[11px] text-foreground-secondary">
                {t('overview.topRules', { rules: topRules.join(' · ') })}
              </p>
            )}
          </CardContent>
        </Card>
        <RecentActivity />
      </section>
    </PageShell>
  )
}

function dayLabel(point) {
  const raw = String(point?.bucket || point?.date || point?.day || '')
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw)
  if (!m) return ''
  return fmtDate(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])), 'd')
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-foreground-secondary">{label}</dt>
      <dd className="font-bold tabular-nums">{value}</dd>
    </div>
  )
}

function Mini({ label, value, className = '' }) {
  return (
    <div>
      <div className={`text-lg font-extrabold tabular-nums ${className}`}>{value}</div>
      <div className="text-[10px] text-foreground-tertiary">{label}</div>
    </div>
  )
}

function RecentActivity() {
  const { t } = useTranslation('admin')
  const { data, isLoading } = useQuery({
    queryKey: ['admin-recent-audit'],
    queryFn: () => adminService.getAuditLogs(0, 3),
    staleTime: 30_000,
  })
  const logs = data?.logs || []

  return (
    <Card>
      <CardContent className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-bold">{t('overview.recentActivity')}</h2>
          <Link to="/admin/audit" className="text-xs font-medium text-accent hover:underline">
            {t('overview.viewAllActivity')}
          </Link>
        </div>
        {isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-5 w-full" />)}
          </div>
        ) : logs.length === 0 ? (
          <p className="py-4 text-center text-xs text-foreground-tertiary">{t('overview.noActivity')}</p>
        ) : (
          <ul className="space-y-2 text-xs">
            {logs.map((log) => (
              <li key={log._id} className="flex justify-between gap-2">
                <span className="min-w-0 truncate">
                  {t(`auditLog.actions.${log.action}`, { defaultValue: log.action })}
                  {log.admin_email ? ` · ${log.admin_email}` : ''}
                </span>
                <time className="shrink-0 text-foreground-tertiary">{fmtDistanceToNowSafe(log.created_at)}</time>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

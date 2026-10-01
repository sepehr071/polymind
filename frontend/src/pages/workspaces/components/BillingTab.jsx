import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { fmtDate } from '@/utils/dateLocale'
import { fmtNumber, fmtCurrency, fmtCurrencyCompact } from '@/utils/persianLocale'
import { prettifyModelName } from '@/utils/modelName'
import { Plus, Receipt, TrendingUp, CalendarClock, AlertTriangle, Wallet, Activity, Info, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'
import Section from '@/components/teams/Section'
import StatTile from '@/components/teams/StatTile'
import { StatTile as TrendStatTile } from '@/components/ui/StatTile'
import { CostValue } from '@/components/ui/CostValue'
import LimitRow from '@/components/teams/LimitRow'
import AddCreditsDialog from '@/components/billing/AddCreditsDialog'
import {
  ChartCard,
  TimeSeriesChart,
  BreakdownBarChart,
  GranularityRangePicker,
} from '@/components/charts'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { workspaceService } from '@/services/workspaceService'
import { useAuth } from '@/context/AuthContext'
import { hasFeature } from '@/utils/featureFlags'
import { PLAN_TIERS, getPlanTier } from '@/constants/plans'

const PAGE_SIZE = 20
const DAY_MS = 86_400_000

function fmtUsd(n) {
  if (n == null || Number.isNaN(Number(n))) return fmtCurrency(0)
  return fmtCurrency(Number(n))
}

function fmtTokens(n) {
  if (n == null || Number.isNaN(Number(n))) return fmtNumber(0)
  const num = Number(n)
  if (num >= 1_000_000) return `${fmtNumber(num / 1_000_000, { decimals: 1 })}M`
  if (num >= 1_000) return `${fmtNumber(num / 1_000, { decimals: 1 })}K`
  return fmtNumber(num)
}

function fmtDateBilling(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return fmtDate(d, 'MMM d, yyyy')
}

function getInitials(name, email) {
  if (name) return name.slice(0, 2).toUpperCase()
  if (email) return email.slice(0, 2).toUpperCase()
  return '??'
}

function isoDateDaysAgo(days) {
  return new Date(Date.now() - days * DAY_MS).toISOString().slice(0, 10)
}

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

/** Localise a daily bucket key for the spend chart axis / tooltip. */
function fmtSpendBucket(iso, granularity) {
  if (!iso) return ''
  if (granularity === 'month') {
    const d = new Date(`${iso}-01T00:00:00`)
    return Number.isNaN(d.getTime()) ? iso : fmtDate(d, 'MMM yyyy')
  }
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : fmtDate(d, 'MMM d')
}

/** ISO week start (Monday) as `YYYY-MM-DD`. */
function weekStartIso(iso) {
  const x = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(x.getTime())) return iso
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7)) // Mon=0 … Sun=6
  // Serialize from LOCAL parts — toISOString() shifts to UTC, which moves the
  // local-midnight Monday onto the previous day for positive-offset timezones.
  const p = (n) => String(n).padStart(2, '0')
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}`
}

/**
 * Roll the backend's day-grained `daily[]` (`{date, cost_usd, total_tokens}`)
 * into the chosen granularity. The billing endpoint only emits daily rows, so
 * week/month are an honest client-side aggregation of real data.
 */
function rebucketSpend(daily, granularity) {
  const keyOf = (iso) => {
    if (granularity === 'month') return iso.slice(0, 7)
    if (granularity === 'week') return weekStartIso(iso)
    return iso
  }
  const buckets = new Map()
  for (const r of daily || []) {
    const iso = r.date
    if (!iso) continue
    const k = keyOf(iso)
    const prev = buckets.get(k) || { bucket: k, cost: 0, tokens: 0 }
    prev.cost += Number(r.cost_usd) || 0
    prev.tokens += Number(r.total_tokens) || 0
    buckets.set(k, prev)
  }
  return [...buckets.values()].sort((a, b) =>
    a.bucket < b.bucket ? -1 : a.bucket > b.bucket ? 1 : 0,
  )
}

export default function BillingTab({ wid, workspace, isOwner = false, onUpdated }) {
  const { t } = useTranslation(['projects', 'analytics'])
  const { user } = useAuth()
  // When the `billing_enforcement` flag is on, budgets/caps are HARD limits that
  // block usage — so the advisory "tracking only" copy + amber styling flip to
  // an enforced framing (and the over-target badge goes red/destructive).
  const enforced = hasFeature(user, 'billing_enforcement')
  const queryClient = useQueryClient()
  const [creditOpen, setCreditOpen] = useState(false)
  const [planOpen, setPlanOpen] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const [page, setPage] = useState(0)
  const [range, setRange] = useState(() => ({
    granularity: 'day',
    from: isoDateDaysAgo(30),
    to: todayIso(),
  }))

  // Backend `/billing/usage` window — full timestamps; pin `end` to the close
  // of the chosen day so today's spend is included.
  const apiWindow = useMemo(
    () => ({
      start: range.from ? `${range.from}T00:00:00.000Z` : isoDateDaysAgo(30),
      end: range.to ? `${range.to}T23:59:59.999Z` : todayIso(),
    }),
    [range.from, range.to],
  )

  const usageQ = useQuery({
    queryKey: ['billing', 'usage', wid, apiWindow.start, apiWindow.end],
    queryFn: () =>
      workspaceService.getBillingUsage(wid, { start: apiWindow.start, end: apiWindow.end }),
    enabled: Boolean(wid),
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })

  const ledgerQ = useQuery({
    queryKey: ['billing', 'ledger', wid],
    queryFn: () => workspaceService.getLedger(wid, { limit: 100 }),
    enabled: Boolean(wid),
    staleTime: 60_000,
    // Non-billing-admins can't read the ledger — keep the empty default.
    retry: false,
  })

  const usage = usageQ.data
  const ledger = ledgerQ.data || { entries: [], total_credits_usd: 0 }
  const loading = usageQ.isLoading

  // Daily spend rolled into the selected granularity for the trend chart.
  const spendSeries = useMemo(
    () => rebucketSpend(usage?.daily, range.granularity),
    [usage?.daily, range.granularity],
  )

  // Spend-by-team (DB project) breakdown rows for the bar chart.
  const projectRows = useMemo(
    () =>
      (usage?.by_project || []).map((r) => ({
        id: r.project_id || 'unfiled',
        label:
          r.name ||
          (r.project_id
            ? t('workspaceSettings.billing.unknownProject')
            : t('workspaceSettings.billing.unfiledProject')),
        cost: Number(r.total_cost) || 0,
      })),
    [usage?.by_project, t],
  )

  const modelRows = useMemo(
    () =>
      (usage?.by_model || []).map((r) => ({
        key: r.model || 'unknown',
        label: r.model
          ? prettifyModelName(r.model)
          : t('workspaceSettings.billing.unknownModel'),
        cost: Number(r.total_cost) || 0,
      })),
    [usage?.by_model, t],
  )

  const byUser = useMemo(() => (usage?.by_user || []).slice(0, 10), [usage?.by_user])

  // Cascade block (`/billing/usage.cascade`): per-team budgets + spend under the
  // company budget, surfaced as a mini-table when teams carry their own budgets.
  const cascade = usage?.cascade || null
  const cascadeTeams = useMemo(
    () => (cascade?.teams || []).filter(Boolean),
    [cascade],
  )

  const totals = usage?.totals || {}
  const spendMtd = Number(totals.cost_usd) || 0
  const tokensMtd = Number(totals.total_tokens) || 0
  const messagesMtd = Number(totals.messages) || 0
  const seatsTotal = Number(workspace?.seats_total) || 0
  const seatsUsed = Number(workspace?.seats_used) || 0
  const budget = Number(workspace?.budget_mtd_usd) || 0

  // Month-to-date budget posture (burn-rate, projected month-end, breaches).
  // Always calendar-month-scoped server-side — independent of the trend range
  // picker, which only drives the spend chart / breakdown windows above.
  const budgetPosture = usage?.budget || null
  const planTierRaw = (workspace?.plan_tier || workspace?.plan || 'free').toLowerCase()
  // New tiers come from PLAN_TIERS; legacy free/team still resolve to their own
  // keys; anything else falls back to the raw stored string.
  const planTierLabelKey =
    getPlanTier(planTierRaw)?.labelKey ||
    (['free', 'team'].includes(planTierRaw)
      ? `workspaceSettings.billing.planDialog.tier${planTierRaw.charAt(0).toUpperCase()}${planTierRaw.slice(1)}`
      : null)
  const planTier = planTierLabelKey ? t(planTierLabelKey) : (workspace?.plan_tier || workspace?.plan || '')
  const renewsAt = workspace?.renews_at

  // Plan allowance (profit redesign): the `plan` block on /billing/usage carries
  // the monthly allowance + remaining. `remaining_usd` is server-computed; fall
  // back to allowance − spend MTD when the backend omits it (older payloads).
  const planBlock = usage?.plan || null
  const planAllowance =
    planBlock?.allowance_usd != null ? Number(planBlock.allowance_usd) : null
  const planRemaining =
    planBlock?.remaining_usd != null
      ? Number(planBlock.remaining_usd)
      : planAllowance != null
        ? planAllowance - spendMtd
        : null

  const credits = usage?.credits || {}
  const creditRemaining = credits.remaining_usd != null ? Number(credits.remaining_usd) : Number(workspace?.credits_balance_usd ?? ledger.total_credits_usd) || 0
  const creditLifetimeTopups = credits.lifetime_topups_usd != null ? Number(credits.lifetime_topups_usd) : null
  const creditLifetimeSpend = credits.lifetime_spend_usd != null ? Number(credits.lifetime_spend_usd) : null
  // Balance health: overdrawn = spent past what was added; low = under 10% of
  // lifetime top-ups left. Both gate a callout under the balance figure.
  const hasLifetime = creditLifetimeTopups != null && creditLifetimeSpend != null
  const overdrawn = creditRemaining < 0
  const lowBalance =
    !overdrawn &&
    creditLifetimeTopups != null &&
    creditLifetimeTopups > 0 &&
    creditRemaining < creditLifetimeTopups * 0.1

  const pagedLedger = useMemo(() => {
    const all = ledger.entries || []
    const start = page * PAGE_SIZE
    return all.slice(start, start + PAGE_SIZE)
  }, [ledger, page])
  const totalPages = Math.max(
    1,
    Math.ceil((ledger.entries?.length || 0) / PAGE_SIZE),
  )

  async function handleAddCredits({ amount, type, note }) {
    const num = Number(amount)
    await workspaceService.addCredits(wid, num, note, type)
    toast.success(
      type === 'refund' || num < 0
        ? t('workspaceSettings.billing.addCreditsDialog.toastRecorded', { amount: fmtUsd(num) })
        : t('workspaceSettings.billing.addCreditsDialog.toastAdded', { amount: fmtUsd(num) }),
    )
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['billing', 'usage', wid] }),
      queryClient.invalidateQueries({ queryKey: ['billing', 'ledger', wid] }),
    ])
  }

  if (loading) {
    return (
      <div className="px-4 py-6 text-sm text-fg-3">{t('workspaceSettings.billing.loading')}</div>
    )
  }

  return (
    <div className="space-y-6">
      {/* How billing works — prepaid-credit primer so an owner can answer
          "how am I charged?" and "how do I add money?" without leaving the tab. */}
      <BillingHowItWorks t={t} />

      {/* Plan card */}
      <Section title={t('workspaceSettings.billing.planTitle')} hint={t('workspaceSettings.billing.planHint')}>
        <div className="flex items-center gap-4">
          <div className="flex-1 min-w-0">
            <div className="mb-1 flex items-center gap-2">
              <span className="text-lg font-semibold text-fg-0 capitalize">
                {planTier}
              </span>
              <span className="inline-flex items-center rounded-full bg-ok/15 px-2 py-0.5 text-[11px] font-semibold text-ok">
                {t('workspaceSettings.billing.planActiveBadge')}
              </span>
            </div>
            <span className="text-xs text-fg-3">
              {seatsTotal > 0
                ? t('workspaceSettings.billing.seatsLabel', { count: seatsTotal })
                : t('workspaceSettings.billing.payAsYouGo')}
              {renewsAt ? ` · ${t('workspaceSettings.billing.renewsAt', { date: fmtDateBilling(renewsAt) })}` : ''}
            </span>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={!isOwner}
            onClick={() => setPlanOpen(true)}
            title={!isOwner ? t('workspaceSettings.security.ownerOnly') : t('workspaceSettings.billing.planSettings')}
          >
            {t('workspaceSettings.billing.planSettings')}
          </Button>
        </div>
      </Section>

      {/* Plan allowance — the monthly $ allowance this plan grants + what's left
          after MTD spend. Enterprise / no-preset plans omit it (allowance null). */}
      {planAllowance != null && (
        <PlanAllowanceSection
          allowance={planAllowance}
          remaining={planRemaining}
          spendMtd={spendMtd}
          enforced={enforced}
          t={t}
        />
      )}

      {/* Credit balance */}
      <Section
        title={t('workspaceSettings.billing.creditTitle')}
        hint={t('workspaceSettings.billing.creditHint')}
        action={
          // Funding is platform-admin only (route is require_admin): a workspace
          // owner can no longer self-mint credits. Hide the button for non-admins
          // so it never 403s; the balance itself stays visible to owners.
          user?.role === 'admin' && (
            <Button size="sm" onClick={() => setCreditOpen(true)}>
              <Plus className="h-3.5 w-3.5" />
              {t('workspaceSettings.billing.addCredits')}
            </Button>
          )
        }
      >
        {user?.role !== 'admin' && (
          <p className="mb-3 text-xs leading-snug text-fg-3">
            {t('workspaceSettings.billing.requestCreditsHint')}
          </p>
        )}
        {/* Remaining is the wallet figure; Added/Used give it context. */}
        <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-fg-4">
              {t('workspaceSettings.billing.creditRemaining')}
            </div>
            <div
              className={cn(
                'mt-1.5 text-[26px] font-extrabold leading-none tracking-[-0.01em]',
                overdrawn ? 'text-err' : 'text-fg-0',
              )}
            >
              {fmtUsd(creditRemaining)}
            </div>
          </div>
          {hasLifetime && (
            <div className="flex gap-6">
              <div className="text-end">
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-fg-4">
                  {t('workspaceSettings.billing.balanceAdded')}
                </div>
                <div className="mt-0.5 font-mono tabular-nums text-[14px] text-fg-1">
                  {fmtUsd(creditLifetimeTopups)}
                </div>
              </div>
              <div className="text-end">
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-fg-4">
                  {t('workspaceSettings.billing.balanceUsed')}
                </div>
                <div className="mt-0.5 font-mono tabular-nums text-[14px] text-fg-1">
                  {fmtUsd(creditLifetimeSpend)}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Balance-used bar: lifetime spend against lifetime top-ups. */}
        {hasLifetime && creditLifetimeTopups > 0 && (
          <div className="mt-4">
            <LimitRow
              label={t('workspaceSettings.billing.balanceUsedBar')}
              used={creditLifetimeSpend}
              cap={creditLifetimeTopups}
              over={overdrawn}
              valueFormatter={(n) => fmtUsd(n)}
            />
          </div>
        )}

        {/* Low / overdrawn callout. */}
        {(overdrawn || lowBalance) && (
          <div
            className={cn(
              'mt-3 flex items-start gap-2 rounded-lg border p-3 text-xs',
              overdrawn ? 'border-err/30 bg-err/5' : 'border-warn/30 bg-warn/5',
            )}
          >
            <AlertTriangle
              className={cn('mt-px h-4 w-4 shrink-0', overdrawn ? 'text-err' : 'text-warn')}
            />
            <div>
              <div className={cn('font-medium', overdrawn ? 'text-err' : 'text-warn')}>
                {overdrawn
                  ? t('workspaceSettings.billing.overdrawnTitle')
                  : t('workspaceSettings.billing.lowBalanceTitle')}
              </div>
              <p className="mt-0.5 text-fg-2">
                {overdrawn
                  ? t('workspaceSettings.billing.overdrawnBody')
                  : t('workspaceSettings.billing.lowBalanceBody')}
              </p>
            </div>
          </div>
        )}

      </Section>

      {/* 3-col stat grid — always visible summary */}
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile
          label={t('workspaceSettings.billing.stats.seatsUsed')}
          value={`${fmtNumber(seatsUsed)} / ${seatsTotal ? fmtNumber(seatsTotal) : '∞'}`}
          hint={
            seatsTotal > 0
              ? t('workspaceSettings.billing.seatsAvailable', {
                  count: Math.max(0, seatsTotal - seatsUsed),
                })
              : t('workspaceSettings.billing.noSeatCap')
          }
        />
        <StatTile
          label={t('workspaceSettings.billing.stats.spendMtd')}
          value={fmtCurrencyCompact(spendMtd)}
          hint={
            budget > 0
              ? t(
                  enforced
                    ? 'workspaceSettings.billing.ofBudgetEnforced'
                    : 'workspaceSettings.billing.ofBudgetAdvisory',
                  { amount: fmtCurrencyCompact(budget) },
                )
              : t('workspaceSettings.billing.noBudget')
          }
        />
        <StatTile
          label={t('workspaceSettings.billing.stats.tokensMonth')}
          value={`${fmtTokens(tokensMtd)}`}
          hint={t('workspaceSettings.billing.messagesCount', { count: messagesMtd })}
        />
      </div>

      {/* Top teams stay above the fold — managers care most about this slice. */}
      <ChartCard
        title={t('workspaceSettings.billing.spendByProjectTitle')}
        subtitle={t('workspaceSettings.billing.spendByProjectHint')}
        loading={loading}
        empty={projectRows.length === 0}
        emptyLabel={t('workspaceSettings.billing.spendByProjectEmpty')}
        height={Math.max(160, Math.min(projectRows.length, 8) * 40 + 32)}
      >
        <BreakdownBarChart
          data={projectRows}
          dataKey="cost"
          labelKey="label"
          metricLabel={t('analytics:metrics.cost')}
          valueFormatter={(v) => fmtCurrencyCompact(v)}
        />
      </ChartCard>

      <SpendLimitsSection
        posture={budgetPosture}
        spendMtd={spendMtd}
        budget={budget}
        caps={workspace?.spend_caps || {}}
        isOwner={isOwner}
        enforced={enforced}
        onManage={() => setPlanOpen(true)}
        t={t}
      />

      {/* Progressive disclosure: ledger + deep charts behind one expand. */}
      <div className="rounded-[16px] border border-line bg-bg-2/40">
        <button
          type="button"
          onClick={() => setShowDetails((v) => !v)}
          className="flex w-full items-center justify-between gap-3 px-4 py-3 text-start"
          aria-expanded={showDetails}
        >
          <div>
            <div className="text-[13px] font-semibold text-fg-0">
              {t('workspaceSettings.billingDetails')}
            </div>
            <p className="text-[11px] text-fg-3">
              {t('workspaceSettings.billingDetailsHint')}
            </p>
          </div>
          <ChevronDown
            className={cn(
              'h-4 w-4 shrink-0 text-fg-3 transition-transform',
              showDetails && 'rotate-180',
            )}
          />
        </button>
        {showDetails && (
          <div className="space-y-6 border-t border-line px-4 py-4">
            {ledger.entries && ledger.entries.length > 0 ? (
              <div className="overflow-x-auto rounded-2xl border border-line bg-bg-2/50">
                <table className="w-full text-start text-[13px]">
                  <thead>
                    <tr className="border-b border-line bg-bg-2/50 text-[12px] font-bold text-fg-2">
                      <th className="px-3 py-2.5 text-start">{t('workspaceSettings.billing.transactionHeaders.date')}</th>
                      <th className="px-3 py-2.5 text-start">{t('workspaceSettings.billing.transactionHeaders.type')}</th>
                      <th className="px-3 py-2.5 text-end">{t('workspaceSettings.billing.transactionHeaders.amount')}</th>
                      <th className="px-3 py-2.5 text-start">{t('workspaceSettings.billing.transactionHeaders.note')}</th>
                      <th className="px-3 py-2.5 text-start">{t('workspaceSettings.billing.transactionHeaders.addedBy')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedLedger.map((e) => {
                      const amount = Number(e.amount_usd) || 0
                      const sign = amount >= 0 ? '+' : '−'
                      const typeColors = {
                        top_up: 'bg-ok/15 border-ok/30 text-ok',
                        adjustment: 'bg-warn/15 border-warn/30 text-warn',
                        refund: 'bg-fg-3/15 border-fg-3/30 text-fg-2',
                      }
                      return (
                        <tr
                          key={e._id}
                          className="border-b border-line last:border-0"
                        >
                          <td className="px-3 py-2.5 text-fg-2">
                            {fmtDateBilling(e.created_at)}
                          </td>
                          <td className="px-3 py-2.5">
                            <span
                              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${
                                typeColors[e.type] || typeColors.adjustment
                              }`}
                            >
                              {e.type?.replace('_', ' ')}
                            </span>
                          </td>
                          <td className="px-3 py-2.5 text-end font-mono tabular-nums text-fg-1">
                            {sign}
                            {fmtUsd(Math.abs(amount)).replace('-', '')}
                          </td>
                          <td className="px-3 py-2.5 text-fg-3 truncate max-w-[480px]">
                            {e.note || '—'}
                          </td>
                          <td className="px-3 py-2.5 text-fg-3">
                            {e.added_by_user?.display_name ||
                              e.added_by_user?.email ||
                              '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {totalPages > 1 && (
                  <div className="flex items-center justify-between border-t border-line px-3 py-2 text-xs text-fg-3">
                    <span>
                      {t('workspaceSettings.billing.pageOf', { current: page + 1, total: totalPages })}
                    </span>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={page === 0}
                        onClick={() => setPage((p) => Math.max(0, p - 1))}
                      >
                        {t('admin:users.previous')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={page >= totalPages - 1}
                        onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                      >
                        {t('admin:users.next')}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-1 rounded-2xl border border-dashed border-line bg-bg-2/40 px-4 py-6 text-center">
                <Receipt className="h-5 w-5 text-fg-3" />
                <p className="text-sm text-fg-2">{t('workspaceSettings.billing.ledgerEmptyTitle')}</p>
                <p className="text-[11px] text-fg-3">
                  {t('workspaceSettings.billing.ledgerEmptyHint')}
                </p>
              </div>
            )}

            <ChartCard
              title={t('analytics:chart.spendOverTime')}
              toolbar={
                <GranularityRangePicker
                  value={range}
                  onChange={setRange}
                  disabled={usageQ.isFetching}
                />
              }
              loading={loading}
              empty={spendSeries.length < 2}
              emptyLabel={t('analytics:empty.series')}
              height={240}
            >
              <TimeSeriesChart
                data={spendSeries}
                metrics={[
                  {
                    key: 'cost',
                    label: t('analytics:metrics.cost'),
                    colorIndex: 1,
                    formatter: (v) => fmtCurrency(Number(v) || 0),
                  },
                ]}
                xTickFormatter={(iso) => fmtSpendBucket(iso, range.granularity)}
                tooltipLabelFormatter={(iso) => fmtSpendBucket(iso, range.granularity)}
                yTickFormatter={(v) => fmtCurrency(Number(v) || 0)}
              />
            </ChartCard>

            <Section
              title={t('workspaceSettings.billing.spendByUserTitle')}
              hint={t('workspaceSettings.billing.spendByUserHint')}
            >
              {byUser.length === 0 ? (
                <p className="text-xs text-fg-3">
                  {t('workspaceSettings.billing.spendByUserEmpty')}
                </p>
              ) : (
                <div className="overflow-x-auto rounded-2xl border border-line bg-bg-2/50">
                <table className="w-full text-start text-[13px]">
                  <thead>
                    <tr className="border-b border-line bg-bg-2/50 text-[12px] font-bold text-fg-2">
                      <th className="px-3 py-2.5 w-8 text-start">{t('workspaceSettings.billing.userSpendHeaders.num')}</th>
                      <th className="px-3 py-2.5 text-start">{t('workspaceSettings.billing.userSpendHeaders.user')}</th>
                      <th className="px-3 py-2.5 text-end">{t('workspaceSettings.billing.userSpendHeaders.costMtd')}</th>
                      <th className="px-3 py-2.5 text-end">{t('workspaceSettings.billing.userSpendHeaders.tokens')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byUser.map((u, i) => (
                      <tr
                        key={u.user_id || i}
                        className="border-b border-line last:border-0"
                      >
                        <td className="px-3 py-2.5 text-fg-3 font-mono tabular-nums text-[11px]">
                          {fmtNumber(i + 1)}
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex items-center gap-2.5">
                            <Avatar size="sm">
                              {u.avatar_url && (
                                <AvatarImage src={u.avatar_url} alt={u.display_name || u.email} />
                              )}
                              <AvatarFallback className="text-[10px]">
                                {getInitials(u.display_name, u.email)}
                              </AvatarFallback>
                            </Avatar>
                            <div className="flex flex-col min-w-0">
                              <span className="text-fg-1 truncate">
                                {u.display_name || u.email || t('workspaceSettings.billing.unknownUser')}
                              </span>
                              {u.display_name && u.email && (
                                <span className="text-[11px] text-fg-3 truncate">
                                  {u.email}
                                </span>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="px-3 py-2.5 text-end font-mono tabular-nums text-fg-1">
                          {fmtUsd(u.total_cost)}
                        </td>
                        <td className="px-3 py-2.5 text-end font-mono tabular-nums text-fg-3">
                          {fmtTokens(u.total_tokens)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              )}
            </Section>

            <ChartCard
              title={t('workspaceSettings.billing.spendByModelTitle')}
              subtitle={t('workspaceSettings.billing.spendByModelHint')}
              loading={loading}
              empty={modelRows.length === 0}
              emptyLabel={t('workspaceSettings.billing.spendByModelEmpty')}
              height={Math.max(160, Math.min(modelRows.length, 8) * 40 + 32)}
            >
              <BreakdownBarChart
                data={modelRows}
                dataKey="cost"
                labelKey="label"
                metricLabel={t('analytics:metrics.cost')}
                valueFormatter={(v) => fmtCurrencyCompact(v)}
              />
            </ChartCard>

            {cascadeTeams.length > 0 && (
              <CascadeTeamsSection teams={cascadeTeams} enforced={enforced} t={t} />
            )}
          </div>
        )}
      </div>

      <AddCreditsDialog
        open={creditOpen}
        onClose={() => setCreditOpen(false)}
        scope="owner"
        currentBalance={creditRemaining}
        onConfirm={handleAddCredits}
      />

      <ManagePlanDialog
        open={planOpen}
        onOpenChange={setPlanOpen}
        workspace={workspace}
        wid={wid}
        isAdmin={user?.role === 'admin'}
        onSaved={(updated) => {
          onUpdated?.(updated)
          // Budget/cap edits change the server-computed posture + breaches —
          // refetch so the spend-limits section reflects the new caps.
          queryClient.invalidateQueries({ queryKey: ['billing', 'usage', wid] })
        }}
      />
    </div>
  )
}

/**
 * BillingHowItWorks — compact prepaid-credit primer. The model (owner records
 * manual top-ups, usage draws the balance down, remaining = added − used) isn't
 * obvious from the charts alone, so this answers it inline at the top of the tab.
 */
function BillingHowItWorks({ t }) {
  const steps = [
    {
      icon: Wallet,
      title: t('workspaceSettings.billing.howItWorks.step1Title'),
      body: t('workspaceSettings.billing.howItWorks.step1Body'),
    },
    {
      icon: Activity,
      title: t('workspaceSettings.billing.howItWorks.step2Title'),
      body: t('workspaceSettings.billing.howItWorks.step2Body'),
    },
    {
      icon: Plus,
      title: t('workspaceSettings.billing.howItWorks.step3Title'),
      body: t('workspaceSettings.billing.howItWorks.step3Body'),
    },
  ]
  return (
    <div className={cn('rounded-xl p-4')} style={solidPanelSx({ radius: RADII.surface })}>
      <div className="mb-3 flex items-center gap-1.5 text-fg-1">
        <Info className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-semibold">
          {t('workspaceSettings.billing.howItWorks.title')}
        </h3>
      </div>
      <ol className="grid gap-3.5 sm:grid-cols-3">
        {steps.map((s, i) => (
          <li key={i} className="flex gap-2.5">
            <IconTile icon={s.icon} tone="accent" size="md" />
            <div className="min-w-0">
              <div className="text-xs font-medium text-fg-1">{s.title}</div>
              <p className="mt-0.5 text-xs leading-snug text-fg-3">{s.body}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

/**
 * PlanAllowanceSection — the plan's monthly $ allowance and what remains after
 * month-to-date spend, on the owner-only `/billing/usage.plan` block. Uses the
 * same CostValue + LimitRow idiom as SpendLimitsSection. Only rendered when an
 * allowance is set (Enterprise / bespoke plans pass none).
 */
function PlanAllowanceSection({ allowance, remaining, spendMtd, enforced = false, t }) {
  const remain = remaining != null ? remaining : allowance - spendMtd
  const over = remain < 0
  return (
    <Section
      title={t('workspaceSettings.billing.allowance.title')}
      hint={t('workspaceSettings.billing.allowance.hint')}
    >
      <div className="flex flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <TrendStatTile
            icon={Wallet}
            label={t('workspaceSettings.billing.allowance.label')}
            value={<CostValue usd={allowance} />}
          />
          <TrendStatTile
            icon={Activity}
            label={t('workspaceSettings.billing.stats.spendMtd')}
            value={<CostValue usd={spendMtd} />}
          />
          <TrendStatTile
            icon={TrendingUp}
            label={t('workspaceSettings.billing.allowance.remainingLabel')}
            value={
              <span className={over ? 'text-err' : 'text-ok'}>
                <CostValue usd={remain} />
              </span>
            }
          />
        </div>
        <LimitRow
          label={t('workspaceSettings.billing.allowance.label')}
          used={spendMtd}
          cap={allowance}
          over={over}
          overTone={enforced ? 'error' : 'warn'}
          overBadge={t(
            enforced
              ? 'workspaceSettings.billing.limits.overBudgetEnforced'
              : 'workspaceSettings.billing.limits.aboveTarget',
          )}
          valueFormatter={(n) => fmtUsd(n)}
        />
      </div>
    </Section>
  )
}

/**
 * SpendLimitsSection — budget posture (burn-rate / projected month-end /
 * over-budget) + real workspace-budget and per-user / per-model caps, driven by
 * the server-computed `budget` block on `/billing/usage`. Caps are edited
 * (owner-only) via the Plan settings dialog. Month-to-date scoped server-side,
 * so it stays independent of the trend range picker.
 */
function SpendLimitsSection({
  posture,
  spendMtd,
  budget,
  caps,
  isOwner,
  enforced = false,
  onManage,
  t,
}) {
  // Enforcement flips the advisory framing: the per-bar note, the over-target
  // badge text, the section hint, and the over-state colour (amber → red).
  const noteKey = enforced
    ? 'workspaceSettings.billing.limits.enforced'
    : 'workspaceSettings.billing.limits.trackingOnly'
  const overBadgeKey = enforced
    ? 'workspaceSettings.billing.limits.overBudgetEnforced'
    : 'workspaceSettings.billing.limits.aboveTarget'
  const overTone = enforced ? 'error' : 'warn'
  const burnRate = Number(posture?.burn_rate_usd_per_day) || 0
  const projected = Number(posture?.projected_month_end_usd) || 0
  const overBudget = Boolean(posture?.over_budget)
  const projectedOver = Boolean(posture?.projected_over_budget)
  // `budget_used_pct` is null when no budget is configured.
  const usedPct = posture?.budget_used_pct
  const budgetAmt = Number(posture?.budget_mtd_usd) || budget || 0
  // Server spend (calendar MTD) wins; fall back to the totals-derived value.
  const spend = posture?.spend_mtd_usd != null ? Number(posture.spend_mtd_usd) : spendMtd

  const perUserCap = Number(caps?.per_user_usd) || 0
  const perModelCap = Number(caps?.per_model_usd) || 0
  const userBreaches = posture?.caps?.user_breaches || []
  const modelBreaches = posture?.caps?.model_breaches || []
  // Worst offender per cap dimension — the bar tracks the highest single
  // spender against the cap (rows are server-sorted descending by spend).
  const topUserSpend = Number(userBreaches[0]?.spend) || 0
  const topModelSpend = Number(perModelCap ? modelBreaches[0]?.spend : 0) || 0

  const hasAnyLimit = budgetAmt > 0 || perUserCap > 0 || perModelCap > 0
  const action = isOwner ? (
    <Button variant="outline" size="sm" onClick={onManage}>
      {t('workspaceSettings.billing.limits.manage')}
    </Button>
  ) : null

  return (
    <Section
      title={t('workspaceSettings.billing.spendLimitsTitle')}
      hint={t(
        enforced
          ? 'workspaceSettings.billing.spendLimitsEnforcedHint'
          : 'workspaceSettings.billing.spendLimitsHint',
      )}
      action={action}
    >
      {!hasAnyLimit ? (
        <div className="flex flex-col items-center gap-1 rounded-lg border border-dashed border-line bg-bg-2/40 px-4 py-6 text-center">
          <p className="text-sm text-fg-2">
            {t('workspaceSettings.billing.limits.noBudgetTitle')}
          </p>
          <p className="text-[11px] text-fg-3">
            {isOwner
              ? t('workspaceSettings.billing.limits.noBudgetHintOwner')
              : t('workspaceSettings.billing.limits.noBudgetHint')}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {/* Posture tiles — only meaningful once a budget exists. */}
          {budgetAmt > 0 && (
            <div className="grid gap-3 sm:grid-cols-3">
              <TrendStatTile
                icon={TrendingUp}
                label={t('workspaceSettings.billing.limits.burnRate')}
                value={<CostValue usd={burnRate} />}
                subtitle={t('workspaceSettings.billing.limits.burnRateHint')}
              />
              <TrendStatTile
                icon={CalendarClock}
                label={t('workspaceSettings.billing.limits.projected')}
                value={<CostValue usd={projected} />}
                subtitle={
                  usedPct != null
                    ? t(
                        enforced
                          ? 'workspaceSettings.billing.ofBudgetEnforced'
                          : 'workspaceSettings.billing.ofBudgetAdvisory',
                        { amount: fmtUsd(budgetAmt) },
                      )
                    : undefined
                }
              />
              <TrendStatTile
                icon={AlertTriangle}
                label={t('workspaceSettings.billing.limits.status')}
                // Advisory posture reads AMBER; an ENFORCED over-state reads RED
                // (usage is actually blocked once the flag is on).
                value={
                  <span
                    className={
                      overBudget || projectedOver
                        ? enforced
                          ? 'text-err'
                          : 'text-warn'
                        : 'text-ok'
                    }
                  >
                    {overBudget
                      ? t('workspaceSettings.billing.limits.statusOver')
                      : projectedOver
                        ? t('workspaceSettings.billing.limits.statusProjectedOver')
                        : t('workspaceSettings.billing.limits.statusOnTrack')}
                  </span>
                }
                subtitle={
                  usedPct != null
                    ? t('workspaceSettings.billing.limits.usedPct', {
                        pct: fmtNumber(usedPct, { decimals: 0 }),
                      })
                    : undefined
                }
              />
            </div>
          )}

          {/* Budget-vs-actual bars. Each carries a persistent "tracking only —
              not enforced" note so the advisory nature is never buried. */}
          <div className="flex flex-col gap-3">
            {budgetAmt > 0 && (
              <LimitRow
                label={t('workspaceSettings.billing.limits.workspaceMonthly')}
                used={spend}
                cap={budgetAmt}
                over={overBudget}
                overTone={overTone}
                overBadge={t(overBadgeKey)}
                note={t(noteKey)}
                valueFormatter={(n) => fmtUsd(n)}
                trailing={
                  usedPct != null ? (
                    <span className="rounded-full bg-bg-3 px-1.5 py-px text-[10px] text-fg-3">
                      {t('workspaceSettings.billing.limits.usedPct', {
                        pct: fmtNumber(usedPct, { decimals: 0 }),
                      })}
                    </span>
                  ) : null
                }
              />
            )}
            {perUserCap > 0 && (
              <LimitRow
                label={t('workspaceSettings.billing.limits.perUser')}
                used={topUserSpend}
                cap={perUserCap}
                over={userBreaches.length > 0}
                overTone={overTone}
                overBadge={t(overBadgeKey)}
                note={t(noteKey)}
                valueFormatter={(n) => fmtUsd(n)}
              />
            )}
            {perModelCap > 0 && (
              <LimitRow
                label={t('workspaceSettings.billing.limits.perModel')}
                used={topModelSpend}
                cap={perModelCap}
                over={modelBreaches.length > 0}
                overTone={overTone}
                overBadge={t(overBadgeKey)}
                note={t(noteKey)}
                valueFormatter={(n) => fmtUsd(n)}
              />
            )}
          </div>

          {/* Cap breaches — who/what is at or over their monthly cap. */}
          {(userBreaches.length > 0 || modelBreaches.length > 0) && (
            <div className="rounded-lg border border-warn/30 bg-warn/5 p-3">
              <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-warn">
                <AlertTriangle className="h-3.5 w-3.5" />
                {t('workspaceSettings.billing.limits.breachesTitle')}
              </div>
              <ul className="flex flex-col gap-1.5 text-xs">
                {userBreaches.map((b) => (
                  <li
                    key={`u-${b.id}`}
                    className="flex items-center justify-between gap-3"
                  >
                    <span className="truncate text-fg-1">
                      {t('workspaceSettings.billing.limits.breachUser', {
                        name: b.label,
                      })}
                    </span>
                    <span className="font-mono tabular-nums text-warn">
                      {fmtUsd(b.spend)} / {fmtUsd(b.cap)}
                    </span>
                  </li>
                ))}
                {modelBreaches.map((b) => (
                  <li
                    key={`m-${b.id}`}
                    className="flex items-center justify-between gap-3"
                  >
                    <span className="truncate text-fg-1" dir="ltr">
                      {t('workspaceSettings.billing.limits.breachModel', {
                        name: b.label,
                      })}
                    </span>
                    <span className="font-mono tabular-nums text-warn">
                      {fmtUsd(b.spend)} / {fmtUsd(b.cap)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Section>
  )
}

/**
 * CascadeTeamsSection — per-team budgets + spend rolled under the company budget
 * (the `/billing/usage.cascade.teams` block). A team carries its own
 * `{budget, spend, remaining}`; a null budget renders as "—" (no team cap). When
 * enforcement is on an over-budget team reads red, else amber (advisory).
 */
function CascadeTeamsSection({ teams, enforced, t }) {
  return (
    <Section
      title={t('workspaceSettings.billing.cascade.title')}
      hint={t(
        enforced
          ? 'workspaceSettings.billing.cascade.hintEnforced'
          : 'workspaceSettings.billing.cascade.hint',
      )}
    >
      <div className="overflow-x-auto rounded-2xl border border-line bg-bg-2/50">
      <table className="w-full text-start text-[13px]">
        <thead>
          <tr className="border-b border-line bg-bg-2/50 text-[12px] font-bold text-fg-2">
            <th className="px-3 py-2.5 text-start">{t('workspaceSettings.billing.cascade.headers.team')}</th>
            <th className="px-3 py-2.5 text-end">{t('workspaceSettings.billing.cascade.headers.budget')}</th>
            <th className="px-3 py-2.5 text-end">{t('workspaceSettings.billing.cascade.headers.spend')}</th>
            <th className="px-3 py-2.5 text-end">{t('workspaceSettings.billing.cascade.headers.remaining')}</th>
          </tr>
        </thead>
        <tbody>
          {teams.map((tm, i) => {
            const hasBudget =
              tm.budget != null && Number.isFinite(Number(tm.budget))
            const remaining =
              tm.remaining != null ? Number(tm.remaining) : null
            const over = hasBudget && remaining != null && remaining < 0
            return (
              <tr
                key={tm.project_id || i}
                className="border-b border-line last:border-0"
              >
                <td className="px-3 py-2.5 text-fg-1">
                  {tm.name || t('workspaceSettings.billing.unknownProject')}
                </td>
                <td className="px-3 py-2.5 text-end font-mono tabular-nums text-fg-2">
                  {hasBudget ? fmtUsd(Number(tm.budget)) : '—'}
                </td>
                <td className="px-3 py-2.5 text-end font-mono tabular-nums text-fg-1">
                  {fmtUsd(Number(tm.spend) || 0)}
                </td>
                <td
                  className={cn(
                    'px-3 py-2.5 text-end font-mono tabular-nums',
                    over ? (enforced ? 'text-err' : 'text-warn') : 'text-fg-2',
                  )}
                >
                  {remaining != null ? fmtUsd(remaining) : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      </div>
    </Section>
  )
}

function ManagePlanDialog({ open, onOpenChange, workspace, wid, isAdmin = false, onSaved }) {
  const { t } = useTranslation('projects')
  const [planTier, setPlanTier] = useState('starter')
  const [seatsTotal, setSeatsTotal] = useState('')
  const [budget, setBudget] = useState('')
  const [perUserCap, setPerUserCap] = useState('')
  const [perModelCap, setPerModelCap] = useState('')
  const [renewsAt, setRenewsAt] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (!open || !workspace) return
    setPlanTier(workspace.plan_tier || workspace.plan || 'free')
    setSeatsTotal(
      workspace.seats_total != null ? String(workspace.seats_total) : '',
    )
    setBudget(
      workspace.budget_mtd_usd != null && Number(workspace.budget_mtd_usd) > 0
        ? String(workspace.budget_mtd_usd)
        : '',
    )
    const caps = workspace.spend_caps || {}
    setPerUserCap(caps.per_user_usd != null ? String(caps.per_user_usd) : '')
    setPerModelCap(caps.per_model_usd != null ? String(caps.per_model_usd) : '')
    if (workspace.renews_at) {
      try {
        const d = new Date(workspace.renews_at)
        if (!Number.isNaN(d.getTime())) {
          setRenewsAt(d.toISOString().slice(0, 10))
        } else {
          setRenewsAt('')
        }
      } catch {
        setRenewsAt('')
      }
    } else {
      setRenewsAt('')
    }
    setErr(null)
  }, [open, workspace])

  async function handleSubmit(e) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      // Tier + monthly allowance (budget) are admin-only — never include them in
      // a non-admin payload, so a disabled control can't be bypassed via state.
      const payload = {}
      if (isAdmin) payload.plan_tier = planTier
      if (seatsTotal !== '') {
        const n = Number(seatsTotal)
        if (!Number.isFinite(n) || n < 0) {
          throw new Error(t('workspaceSettings.billing.planDialog.errorSeatsNonNeg'))
        }
        payload.seats_total = n
      } else {
        payload.seats_total = null
      }
      if (isAdmin) {
        if (budget !== '') {
          const n = Number(budget)
          if (!Number.isFinite(n) || n < 0) {
            throw new Error(t('workspaceSettings.billing.planDialog.errorBudgetNonNeg'))
          }
          payload.budget_mtd_usd = n
        } else {
          payload.budget_mtd_usd = null
        }
      }
      // Per-user / per-model spend caps. Empty/0 => disabled (backend coerces
      // to null). Send the whole `spend_caps` object so a cleared field clears.
      const parseCap = (raw, errKey) => {
        if (raw === '') return null
        const n = Number(raw)
        if (!Number.isFinite(n) || n < 0) {
          throw new Error(t(errKey))
        }
        return n
      }
      payload.spend_caps = {
        per_user_usd: parseCap(
          perUserCap,
          'workspaceSettings.billing.planDialog.errorCapNonNeg',
        ),
        per_model_usd: parseCap(
          perModelCap,
          'workspaceSettings.billing.planDialog.errorCapNonNeg',
        ),
      }
      if (renewsAt) {
        try {
          const d = new Date(`${renewsAt}T00:00:00`)
          if (!Number.isNaN(d.getTime())) {
            payload.renews_at = d.toISOString()
          }
        } catch {
          // ignore — leave as not-set
        }
      } else {
        payload.renews_at = null
      }
      const updated = await workspaceService.update(wid, payload)
      onSaved?.(updated)
      toast.success(t('workspaceSettings.billing.planDialog.toastSaved'))
      onOpenChange(false)
    } catch (ex) {
      setErr(
        ex?.response?.data?.error ||
          ex?.message ||
          t('workspaceSettings.billing.planDialog.errorSaveFailed'),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('workspaceSettings.billing.planDialog.title')}</DialogTitle>
        </DialogHeader>
        <p className="-mt-1 text-xs leading-snug text-fg-3">
          {t('workspaceSettings.billing.planDialog.intro')}
        </p>
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Plan & seats — subscription labels (tier / seats / renewal). */}
          <div className="space-y-3">
            <div className="space-y-0.5">
              <h4 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-4">
                {t('workspaceSettings.billing.planDialog.sectionPlan')}
              </h4>
              <p className="text-[11px] text-fg-3">
                {t('workspaceSettings.billing.planDialog.sectionPlanHint')}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="plan-tier">{t('workspaceSettings.billing.planDialog.planLabel')}</Label>
              {/* Tier + allowance are admin-only — mirror the credit "Add" gate.
                  Non-admin owners see the current tier read-only. */}
              <Select value={planTier} onValueChange={setPlanTier} disabled={!isAdmin}>
                <SelectTrigger
                  id="plan-tier"
                  title={!isAdmin ? t('workspaceSettings.security.adminOnly') : undefined}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PLAN_TIERS.map((tier) => (
                    <SelectItem key={tier.key} value={tier.key}>
                      <span className="flex w-full items-center justify-between gap-3">
                        <span>{t(tier.labelKey)}</span>
                        <span className="text-[11px] text-fg-3">
                          {tier.allowanceUsd != null
                            ? t('workspaceSettings.billing.planDialog.tierAllowanceHint', {
                                amount: fmtCurrency(tier.allowanceUsd),
                              })
                            : t('workspaceSettings.billing.planDialog.tierAllowanceCustom')}
                        </span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {!isAdmin && (
                <p className="text-[11px] text-fg-3">
                  {t('workspaceSettings.billing.planDialog.tierAdminOnly')}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="plan-seats">{t('workspaceSettings.billing.planDialog.seatsLabel')}</Label>
              <Input
                id="plan-seats"
                type="number"
                min="0"
                step="1"
                value={seatsTotal}
                onChange={(e) => setSeatsTotal(e.target.value)}
                placeholder={t('workspaceSettings.billing.planDialog.seatsPlaceholder')}
              />
              <p className="text-[11px] text-fg-3">
                {t('workspaceSettings.billing.planDialog.seatsHint')}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="plan-renews">
                {t('workspaceSettings.billing.planDialog.renewsAtLabel')}
              </Label>
              <Input
                id="plan-renews"
                type="date"
                value={renewsAt}
                onChange={(e) => setRenewsAt(e.target.value)}
              />
            </div>
          </div>

          {/* Spend controls — tracking targets / alerts, not enforced gates. */}
          <div className="space-y-3 border-t border-line pt-4">
            <div className="space-y-0.5">
              <h4 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-4">
                {t('workspaceSettings.billing.planDialog.sectionSpend')}
              </h4>
              <p className="text-[11px] text-fg-3">
                {t('workspaceSettings.billing.planDialog.sectionSpendHint')}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="plan-budget">
                {t('workspaceSettings.billing.planDialog.budgetLabel')}
              </Label>
              <Input
                id="plan-budget"
                type="number"
                min="0"
                step="0.01"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                disabled={!isAdmin}
                title={!isAdmin ? t('workspaceSettings.security.adminOnly') : undefined}
                placeholder={t('workspaceSettings.billing.planDialog.budgetPlaceholder')}
              />
              <p className="text-[11px] text-fg-3">
                {!isAdmin
                  ? t('workspaceSettings.billing.planDialog.budgetAdminOnly')
                  : t('workspaceSettings.billing.planDialog.budgetHint')}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="plan-cap-user">
                  {t('workspaceSettings.billing.planDialog.perUserCapLabel')}
                </Label>
                <Input
                  id="plan-cap-user"
                  type="number"
                  min="0"
                  step="0.01"
                  value={perUserCap}
                  onChange={(e) => setPerUserCap(e.target.value)}
                  placeholder={t('workspaceSettings.billing.planDialog.capPlaceholder')}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="plan-cap-model">
                  {t('workspaceSettings.billing.planDialog.perModelCapLabel')}
                </Label>
                <Input
                  id="plan-cap-model"
                  type="number"
                  min="0"
                  step="0.01"
                  value={perModelCap}
                  onChange={(e) => setPerModelCap(e.target.value)}
                  placeholder={t('workspaceSettings.billing.planDialog.capPlaceholder')}
                />
              </div>
            </div>
            <p className="text-[11px] text-fg-3">
              {t('workspaceSettings.billing.planDialog.capHint')}
            </p>
          </div>

          {err && <p className="text-sm text-err">{err}</p>}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              {t('common:actions.cancel')}
            </Button>
            <Button type="submit" disabled={busy}>
              {busy
                ? t('workspaceSettings.general.saving')
                : t('workspaceSettings.billing.planDialog.saveButton')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  ShieldAlert,
  ShieldX,
  ShieldCheck,
  ShieldQuestion,
  ChevronDown,
} from 'lucide-react'
import { adminService } from '../../services/adminService'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { StatTile } from '@/components/ui/StatTile'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { fmtDate } from '@/utils/dateLocale'
import { fmtNumber } from '@/utils/persianLocale'
import { SEVERITY_TONES, SeverityBadge, ActionBadge } from '@/components/dlp/badges'
import PageShell from '@/components/layout/PageShell'

const PAGE_SIZE = 50

const shortId = (v) => (v ? String(v).slice(0, 8) : '—')

// Severity/action badge tones come from the canonical map in
// components/dlp/badges.jsx (single source of truth so the same semantic =
// same colour app-wide). SEVERITY_TONES is also reused to derive the bar-chart
// fill colour below. Review-status has no badge equivalent, so it stays local.
const REVIEW_STATUS_COLORS = {
  open: 'bg-background-tertiary text-foreground-secondary border-border',
  reviewed: 'bg-accent/15 text-accent border-accent/30',
  dismissed: 'bg-background-tertiary text-foreground-tertiary border-border',
  escalated: 'bg-warning/15 text-warning border-warning/30',
}

const REVIEW_STATUSES = ['open', 'reviewed', 'dismissed', 'escalated']

export default function DLPDashboardPage() {
  const { t } = useTranslation('admin')
  const queryClient = useQueryClient()
  const [days, setDays] = useState(30)
  const [action, setAction] = useState('')
  const [severity, setSeverity] = useState('')
  const [workspaceId, setWorkspaceId] = useState('')
  const [skip, setSkip] = useState(0)
  const [showEvents, setShowEvents] = useState(false)

  const summaryQuery = useQuery({
    queryKey: ['admin-dlp-summary', days],
    queryFn: () => adminService.getDlpSummary(days),
  })

  const eventsQuery = useQuery({
    queryKey: ['admin-dlp-events', days, action, severity, workspaceId, skip],
    queryFn: () =>
      adminService.listDlpEvents({
        days,
        action: action || undefined,
        severity: severity || undefined,
        workspaceId: workspaceId || undefined,
        skip,
        limit: PAGE_SIZE,
      }),
    enabled: showEvents,
  })

  const companiesQuery = useQuery({
    queryKey: ['admin-companies-list'],
    queryFn: () => adminService.listCompanies(days),
  })

  const reviewMutation = useMutation({
    mutationFn: ({ eventId, status }) =>
      adminService.reviewDlpEvent(eventId, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-dlp-events'] })
      toast.success(t('dlp.reviewSaved'))
    },
  })

  const summary = summaryQuery.data || {}
  const events = eventsQuery.data?.rows || []
  const total = eventsQuery.data?.total || 0
  const companies = companiesQuery.data?.companies || []

  const companyName = useMemo(
    () => Object.fromEntries(companies.map((c) => [c._id, c.name])),
    [companies],
  )

  const daily = summary.daily || []
  const maxDaily = Math.max(1, ...daily.map((d) => Number(d?.count || 0)))

  const bySource = Object.entries(summary.by_source || {})
    .map(([key, count]) => [key, Number(count || 0)])
    .filter(([, count]) => count > 0)
  const maxSource = Math.max(1, ...bySource.map(([, count]) => count))

  const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low']
  const bySeverity = SEVERITY_ORDER.map((sev) => [
    sev,
    Number(summary.by_severity?.[sev] || 0),
  ]).filter(([, count]) => count > 0)
  const maxSeverity = Math.max(1, ...bySeverity.map(([, count]) => count))

  const topRules = (summary.top_rules || []).slice(0, 8)

  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '')

  const handleFilterChange = () => setSkip(0)

  return (
    <PageShell width="full">
        <div className="flex justify-end">
          <Select
            value={days.toString()}
            onValueChange={(v) => {
              setDays(Number(v))
              setSkip(0)
            }}
          >
            <SelectTrigger className="w-[150px]" aria-label={t('dlp.title')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">{t('dashboard.last7days')}</SelectItem>
              <SelectItem value="30">{t('dashboard.last30days')}</SelectItem>
              <SelectItem value="90">{t('dashboard.last90days')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Summary tiles — canonical StatTile (count-up on scroll-in). The
            blocked tile reads as a negative signal (error-toned value).
            Skeletons during the first fetch so the tiles never flash a literal 0. */}
        {summaryQuery.isLoading ? (
          <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-[88px] w-full rounded-2xl" />
            ))}
          </div>
        ) : (
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          <StatTile
            icon={ShieldAlert}
            label={t('dlp.statTotal')}
            value={fmtNumber(summary.total ?? 0)}
            animateValue={summaryQuery.isLoading ? undefined : Number(summary.total ?? 0)}
          />
          <StatTile
            icon={ShieldX}
            label={t('dlp.statBlocked')}
            value={fmtNumber(summary.by_action?.block ?? 0)}
            animateValue={summaryQuery.isLoading ? undefined : Number(summary.by_action?.block ?? 0)}
            tone="negative"
          />
          <StatTile
            icon={ShieldQuestion}
            label={t('dlp.statConfirm')}
            value={fmtNumber(summary.by_action?.require_confirm ?? 0)}
            animateValue={summaryQuery.isLoading ? undefined : Number(summary.by_action?.require_confirm ?? 0)}
          />
          <StatTile
            icon={ShieldCheck}
            label={t('dlp.statWarn')}
            value={fmtNumber(summary.by_action?.warn ?? 0)}
            animateValue={summaryQuery.isLoading ? undefined : Number(summary.by_action?.warn ?? 0)}
          />
        </div>
        )}

        {/* Aggregate trends (identity-free) */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-foreground">{t('dlp.trendsTitle')}</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* By day */}
            <Card>
              <CardHeader>
                <CardTitle>{t('dlp.byDay')}</CardTitle>
              </CardHeader>
              <CardContent>
                {summaryQuery.isLoading ? (
                  <Skeleton className="h-24 w-full" />
                ) : daily.length === 0 ? (
                  <p className="text-foreground-secondary text-sm py-6 text-center">
                    {t('dlp.empty')}
                  </p>
                ) : (
                  <div className="flex items-end gap-1 h-24">
                    {daily.map((d) => {
                      const count = Number(d?.count || 0)
                      const pct = (count / maxDaily) * 100
                      return (
                        <div
                          key={d.date}
                          title={`${d.date}: ${count}`}
                          className="flex-1 min-w-[2px] bg-accent/70 hover:bg-accent rounded-t transition-colors"
                          style={{ height: `${Math.max(pct, count > 0 ? 4 : 0)}%` }}
                        />
                      )
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* By source */}
            <Card>
              <CardHeader>
                <CardTitle>{t('dlp.bySource')}</CardTitle>
              </CardHeader>
              <CardContent>
                {summaryQuery.isLoading ? (
                  <Skeleton className="h-24 w-full" />
                ) : bySource.length === 0 ? (
                  <p className="text-foreground-secondary text-sm py-6 text-center">
                    {t('dlp.empty')}
                  </p>
                ) : (
                  <div className="space-y-3">
                    {bySource.map(([key, count]) => (
                      <div key={key} className="space-y-1">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-foreground-secondary">
                            {t(`dlp.source${cap(key)}`, key)}
                          </span>
                          <span className="text-foreground-tertiary tabular-nums">{fmtNumber(count)}</span>
                        </div>
                        <div className="flex h-2 rounded bg-background-tertiary overflow-hidden">
                          <div
                            className="h-full bg-accent"
                            style={{ width: `${(count / maxSource) * 100}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* By severity */}
            <Card>
              <CardHeader>
                <CardTitle>{t('dlp.bySeverity')}</CardTitle>
              </CardHeader>
              <CardContent>
                {summaryQuery.isLoading ? (
                  <Skeleton className="h-24 w-full" />
                ) : bySeverity.length === 0 ? (
                  <p className="text-foreground-secondary text-sm py-6 text-center">
                    {t('dlp.empty')}
                  </p>
                ) : (
                  <div className="space-y-3">
                    {bySeverity.map(([sev, count]) => {
                      const tone = SEVERITY_TONES[sev] || ''
                      const fillClass = tone.split(' ').find((c) => c.startsWith('text-')) || 'text-accent'
                      const labelClass = fillClass
                      return (
                        <div key={sev} className="space-y-1">
                          <div className="flex items-center justify-between text-sm">
                            <span className={labelClass}>{t(`dlp.sev${cap(sev)}`, sev)}</span>
                            <span className="text-foreground-tertiary tabular-nums">{fmtNumber(count)}</span>
                          </div>
                          <div className="flex h-2 rounded bg-background-tertiary overflow-hidden">
                            <div
                              className={`h-full bg-current ${fillClass}`}
                              style={{ width: `${(count / maxSeverity) * 100}%` }}
                            />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Most-matched rules */}
            <Card>
              <CardHeader>
                <CardTitle>{t('dlp.topRules')}</CardTitle>
              </CardHeader>
              <CardContent>
                {summaryQuery.isLoading ? (
                  <Skeleton className="h-24 w-full" />
                ) : topRules.length === 0 ? (
                  <p className="text-foreground-secondary text-sm py-6 text-center">
                    {t('dlp.empty')}
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {topRules.map((r) => (
                      <li key={r.rule_id} className="flex items-center text-sm">
                        <span className="text-foreground truncate font-mono text-xs">{r.rule_id}</span>
                        <span className="ms-auto ps-3 text-foreground-tertiary tabular-nums">
                          {fmtNumber(Number(r.count || 0))}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </div>

        <p className="text-[11px] text-foreground-tertiary">{t('dlp.subtitle')}</p>

        {/* Individual events (opt-in, privacy-gated) */}
        <Collapsible open={showEvents} onOpenChange={setShowEvents} className="space-y-4">
          <CollapsibleTrigger asChild>
            <Button variant="outline" className="w-full sm:w-auto justify-between gap-2">
              <span>{t('dlp.viewIndividual')}</span>
              <ChevronDown
                className={`h-4 w-4 transition-transform ${showEvents ? 'rotate-180' : ''}`}
              />
            </Button>
          </CollapsibleTrigger>
          <p className="text-xs text-foreground-tertiary">{t('dlp.viewIndividualHint')}</p>
          <CollapsibleContent className="space-y-6">

        {/* Filters */}
        <div className="flex flex-wrap gap-3">
          <Select
            value={action || 'all'}
            onValueChange={(v) => {
              setAction(v === 'all' ? '' : v)
              handleFilterChange()
            }}
          >
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder={t('dlp.filterAction')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('dlp.allActions')}</SelectItem>
              <SelectItem value="block">{t('dlp.actionBlock')}</SelectItem>
              <SelectItem value="require_confirm">{t('dlp.actionConfirm')}</SelectItem>
              <SelectItem value="warn">{t('dlp.actionWarn')}</SelectItem>
              <SelectItem value="redact">{t('dlp.actionRedact')}</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={severity || 'all'}
            onValueChange={(v) => {
              setSeverity(v === 'all' ? '' : v)
              handleFilterChange()
            }}
          >
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder={t('dlp.filterSeverity')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('dlp.allSeverities')}</SelectItem>
              <SelectItem value="critical">{t('dlp.sevCritical')}</SelectItem>
              <SelectItem value="high">{t('dlp.sevHigh')}</SelectItem>
              <SelectItem value="medium">{t('dlp.sevMedium')}</SelectItem>
              <SelectItem value="low">{t('dlp.sevLow')}</SelectItem>
            </SelectContent>
          </Select>

          {companies.length > 0 && (
            <Select
              value={workspaceId || 'all'}
              onValueChange={(v) => {
                setWorkspaceId(v === 'all' ? '' : v)
                handleFilterChange()
              }}
            >
              <SelectTrigger className="w-[200px]">
                <SelectValue placeholder={t('dlp.filterCompany')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('dlp.allCompanies')}</SelectItem>
                {companies.map((c) => (
                  <SelectItem key={c._id} value={c._id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {/* Events table */}
        <Card>
          <CardHeader>
            <CardTitle>{t('dlp.eventsTitle')}</CardTitle>
          </CardHeader>
          <CardContent>
            {eventsQuery.isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : events.length === 0 ? (
              <p className="text-foreground-secondary text-sm py-8 text-center">
                {t('dlp.empty')}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-background-tertiary text-xs uppercase tracking-wide text-foreground-secondary">
                    <tr className="border-b border-border">
                      <th className="text-start py-2.5 px-3 font-bold">{t('dlp.colTime')}</th>
                      <th className="text-start py-2.5 px-3 font-bold">{t('dlp.colCompany')}</th>
                      <th className="text-start py-2.5 px-3 font-bold">{t('dlp.colUser')}</th>
                      <th className="text-start py-2.5 px-3 font-bold">{t('dlp.colSeverity')}</th>
                      <th className="text-start py-2.5 px-3 font-bold">{t('dlp.colAction')}</th>
                      <th className="text-start py-2.5 px-3 font-bold">{t('dlp.colSource')}</th>
                      <th className="text-start py-2.5 px-3 font-bold">{t('dlp.colRule')}</th>
                      <th className="text-start py-2.5 px-3 font-bold">{t('dlp.colSnippet')}</th>
                      <th className="text-start py-2.5 px-3 font-bold">{t('dlp.colStatus')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((ev) => {
                      const topMatch = ev.matches?.[0] || {}
                      const snippet = topMatch.snippet || ''
                      const ruleName = topMatch.rule_name || topMatch.rule_id || '—'
                      const severity = topMatch.severity || '—'
                      const createdAt = ev.created_at
                        ? fmtDate(new Date(ev.created_at), 'MMM d, HH:mm')
                        : '—'
                      const reviewStatus = ev.review_status || 'open'
                      return (
                        <tr key={ev._id} className="border-b border-border/50 hover:bg-background-secondary/50">
                          <td className="py-2 px-3 text-foreground-tertiary whitespace-nowrap">{createdAt}</td>
                          <td
                            className="py-2 px-3 text-foreground max-w-[220px] truncate"
                            title={ev.workspace_name || companyName[ev.workspace_id] || shortId(ev.workspace_id)}
                          >
                            {ev.workspace_name || companyName[ev.workspace_id] || shortId(ev.workspace_id)}
                          </td>
                          <td
                            className="py-2 px-3 text-foreground max-w-[220px] truncate"
                            title={ev.user_email || ev.user_name || shortId(ev.user_id)}
                          >
                            {ev.user_email || ev.user_name || shortId(ev.user_id)}
                          </td>
                          <td className="py-2 px-3">
                            <SeverityBadge severity={severity} />
                          </td>
                          <td className="py-2 px-3">
                            <ActionBadge action={ev.highest_action} />
                          </td>
                          <td className="py-2 px-3 text-foreground-secondary">
                            {t(`dlp.source${ev.source?.charAt(0).toUpperCase() + ev.source?.slice(1)}`, ev.source || '—')}
                          </td>
                          <td className="py-2 px-3 text-foreground-secondary">{ruleName}</td>
                          <td className="py-2 px-3">
                            {snippet ? (
                              <span
                                title={snippet}
                                className="text-foreground-tertiary block cursor-help font-mono text-xs"
                              >
                                {snippet.length > 40 ? snippet.slice(0, 40) + '…' : snippet}
                              </span>
                            ) : (
                              <span className="text-foreground-tertiary">—</span>
                            )}
                          </td>
                          <td className="py-2 px-3 whitespace-nowrap">
                            <div className="flex items-center gap-2">
                              <Badge
                                variant="outline"
                                className={REVIEW_STATUS_COLORS[reviewStatus] || ''}
                              >
                                {t(`dlp.review${reviewStatus.charAt(0).toUpperCase() + reviewStatus.slice(1)}`, reviewStatus)}
                              </Badge>
                              <Select
                                value={reviewStatus}
                                onValueChange={(v) =>
                                  reviewMutation.mutate({ eventId: ev._id, status: v })
                                }
                              >
                                <SelectTrigger className="h-7 w-[130px] text-xs">
                                  <SelectValue placeholder={t('dlp.reviewAction')} />
                                </SelectTrigger>
                                <SelectContent>
                                  {REVIEW_STATUSES.map((s) => (
                                    <SelectItem key={s} value={s}>
                                      {t(`dlp.review${s.charAt(0).toUpperCase() + s.slice(1)}`, s)}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {total > PAGE_SIZE && (
              <div className="flex items-center justify-between mt-4 pt-4 border-t border-border">
                <p className="text-sm text-foreground-secondary tabular-nums">
                  {fmtNumber(skip + 1)}–{fmtNumber(Math.min(skip + PAGE_SIZE, total))} / {fmtNumber(total)}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={skip === 0}
                    onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}
                  >
                    {t('users.previous')}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={skip + PAGE_SIZE >= total}
                    onClick={() => setSkip(skip + PAGE_SIZE)}
                  >
                    {t('users.next')}
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
          </CollapsibleContent>
        </Collapsible>
    </PageShell>
  )
}

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Building2, Users, FolderKanban, Wallet, Search, Loader2, ChevronUp, ChevronDown } from 'lucide-react'
import { adminService } from '@/services/adminService'
import { fmtNumber, fmtCurrency } from '@/utils/persianLocale'
import { fmtDate } from '@/utils/dateLocale'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { StatTile } from '@/components/ui/StatTile'
import { CostValue } from '@/components/ui/CostValue'
import AddCreditsDialog from '@/components/billing/AddCreditsDialog'
import PageShell from '@/components/layout/PageShell'

/**
 * /admin/companies — the holding company directory. Lists every company with
 * headcount/spend/credit summaries; each row drills into `/admin/companies/:wid`.
 */
export default function CompaniesPage() {
  const { t } = useTranslation('analytics')
  const { t: ta } = useTranslation('admin')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState({ key: 'cost', dir: 'desc' })
  const [topup, setTopup] = useState(null)

  const query = useQuery({
    queryKey: ['admin-companies', 30],
    queryFn: () => adminService.listCompanies(30),
    staleTime: 60_000,
  })

  const companies = query.data?.companies || []
  const totals = query.data?.totals || {}

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return companies
    return companies.filter((c) => {
      const haystack = `${c.name || ''} ${c.slug || ''} ${c.domain || ''}`.toLowerCase()
      return haystack.includes(q)
    })
  }, [companies, search])

  const sorted = useMemo(() => {
    const getVal = (c) => {
      switch (sort.key) {
        case 'members':
          return c.member_count || 0
        case 'teams':
          return c.project_count || 0
        case 'chats':
          return c.conversation_count || 0
        case 'cost':
          return c.usage_30d?.cost_usd || 0
        case 'credits':
          return c.credits_balance_usd || 0
        case 'created':
          return new Date(c.created_at).getTime() || 0
        case 'name':
          return (c.name || '').toLowerCase()
        default:
          return 0
      }
    }
    const arr = [...filtered]
    arr.sort((a, b) => {
      const av = getVal(a)
      const bv = getVal(b)
      let cmp
      if (typeof av === 'string' || typeof bv === 'string') {
        cmp = String(av).localeCompare(String(bv))
      } else {
        cmp = av - bv
      }
      return sort.dir === 'asc' ? cmp : -cmp
    })
    return arr
  }, [filtered, sort])

  const toggleSort = (key) => {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'name' ? 'asc' : 'desc' },
    )
  }

  // First-load spinner / hard error before any data is available.
  if (query.isLoading && !query.data) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
      </div>
    )
  }
  if (query.isError && !query.data) {
    return (
      <div className="flex flex-col items-center gap-3 p-12 text-center">
        <p className="text-error">{query.error?.response?.data?.error || t('error.load')}</p>
        <Button variant="outline" size="sm" onClick={() => query.refetch()}>
          {t('error.retry')}
        </Button>
      </div>
    )
  }

  const hasCompanies = companies.length > 0
  const hasResults = sorted.length > 0

  return (
    <PageShell width="full">
        {/* Headcount tiles — counts animate up on scroll-in; credits stays static $. */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            icon={Building2}
            label={t('companiesDirectory.stats.companies')}
            value={fmtNumber(totals.companies)}
            animateValue={totals.companies}
          />
          <StatTile
            icon={Users}
            label={t('companiesDirectory.stats.members')}
            value={fmtNumber(totals.members)}
            animateValue={totals.members}
          />
          <StatTile
            icon={FolderKanban}
            label={t('companiesDirectory.stats.teams')}
            value={fmtNumber(totals.projects)}
            animateValue={totals.projects}
          />
          <StatTile
            icon={Wallet}
            label={t('companiesDirectory.stats.credits')}
            value={fmtCurrency(totals.credits_balance_usd)}
          />
        </div>

        {/* Search */}
        <div className="relative max-w-sm">
          <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-tertiary" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('companiesDirectory.searchPlaceholder')}
            className="ps-9"
          />
        </div>

        {/* Directory table */}
        <Card>
          <CardContent className="p-0">
            {!hasCompanies ? (
              <div className="py-12 text-center text-sm text-foreground-tertiary">
                {t('companiesDirectory.empty')}
              </div>
            ) : !hasResults ? (
              <div className="py-12 text-center text-sm text-foreground-tertiary">
                {t('companiesDirectory.noResults')}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-background-tertiary text-xs uppercase tracking-wide text-foreground-secondary">
                    <tr>
                      <SortHeader
                        align="start"
                        label={t('table.name')}
                        sortKey="name"
                        sort={sort}
                        onSort={toggleSort}
                      />
                      <SortHeader
                        label={t('companiesDirectory.col.members')}
                        sortKey="members"
                        sort={sort}
                        onSort={toggleSort}
                      />
                      <SortHeader
                        label={t('companiesDirectory.col.teams')}
                        sortKey="teams"
                        sort={sort}
                        onSort={toggleSort}
                      />
                      <SortHeader
                        label={t('companiesDirectory.col.chats')}
                        sortKey="chats"
                        sort={sort}
                        onSort={toggleSort}
                      />
                      <SortHeader
                        label={t('companiesDirectory.col.mtdSpend')}
                        sortKey="cost"
                        sort={sort}
                        onSort={toggleSort}
                      />
                      <SortHeader
                        label={t('companiesDirectory.col.credits')}
                        sortKey="credits"
                        sort={sort}
                        onSort={toggleSort}
                      />
                      <th className="px-4 py-2.5 text-end font-bold">
                        {t('companiesDirectory.col.plan')}
                      </th>
                      <SortHeader
                        label={t('companiesDirectory.col.created')}
                        sortKey="created"
                        sort={sort}
                        onSort={toggleSort}
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((c) => {
                      const subline = [c.slug, c.domain].filter(Boolean).join(' · ')
                      return (
                        <tr
                          key={c._id}
                          onClick={() => navigate('/admin/companies/' + c._id)}
                          className="cursor-pointer border-t border-border transition-colors hover:bg-background-tertiary/50"
                        >
                          <td className="px-4 py-2.5">
                            <div className="font-medium text-foreground">{c.name}</div>
                            {subline && (
                              <div className="text-xs text-foreground-tertiary" dir="ltr">
                                {subline}
                              </div>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary">
                            {fmtNumber(c.member_count)}
                          </td>
                          <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary">
                            {fmtNumber(c.project_count)}
                          </td>
                          <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary">
                            {fmtNumber(c.conversation_count)}
                          </td>
                          <td className="px-4 py-2.5 text-end tabular-nums">
                            <CostValue usd={c.usage_30d?.cost_usd} />
                          </td>
                          <td className="px-4 py-2.5 text-end tabular-nums">
                            <CostValue
                              usd={c.credits_balance_usd}
                              className={Number(c.credits_balance_usd) < 0 ? 'font-bold text-error' : 'font-bold text-success'}
                            />
                          </td>
                          <td className="px-4 py-2.5 text-end">
                            {c.plan_tier ? (
                              <Badge variant="secondary">
                                {ta(`overview.plan.${String(c.plan_tier).toLowerCase()}`, { defaultValue: c.plan_tier })}
                              </Badge>
                            ) : (
                              <span className="text-foreground-tertiary">—</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-end text-foreground-secondary">
                            {c.created_at ? fmtDate(new Date(c.created_at), 'd MMM yyyy') : '—'}
                          </td>
                          <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                            <div className="flex gap-1">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="h-7 px-2 text-[11px]"
                                onClick={() => setTopup(c)}
                              >
                                {ta('companyList.topUp')}
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 text-[11px]"
                                onClick={() => navigate('/admin/companies/' + c._id)}
                              >
                                {ta('companyList.details')}
                              </Button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
        <AddCreditsDialog
          open={!!topup}
          onClose={() => setTopup(null)}
          scope="company"
          targetName={topup?.name}
          currentBalance={topup?.credits_balance_usd}
          onConfirm={async ({ amount, type, note, source }) => {
            const res = await adminService.addCompanyCredits(topup._id, {
              amountUsd: amount,
              type,
              note,
              source,
            })
            toast.success(
              ta('addCredits.companySuccess', {
                value: fmtCurrency(res?.credits_balance_usd || 0),
              }),
            )
            queryClient.invalidateQueries({ queryKey: ['admin-companies'] })
          }}
        />
    </PageShell>
  )
}

/** Clickable, sortable column header with an asc/desc caret on the active column. */
function SortHeader({ label, sortKey, sort, onSort, align = 'end' }) {
  const active = sort.key === sortKey
  const Caret = sort.dir === 'asc' ? ChevronUp : ChevronDown
  return (
    <th className={`px-4 py-2.5 font-bold ${align === 'start' ? 'text-start' : 'text-end'}`}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1 transition-colors hover:text-foreground ${
          active ? 'text-foreground' : ''
        } ${align === 'start' ? '' : 'flex-row-reverse'}`}
      >
        <span>{label}</span>
        {active && <Caret className="h-3 w-3" />}
      </button>
    </th>
  )
}

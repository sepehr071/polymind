import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ScrollText, Filter, ChevronLeft, ChevronRight } from 'lucide-react'
import { adminService } from '../../services/adminService'
import { fmtDate } from '../../utils/dateLocale'
import { fmtNumber } from '@/utils/persianLocale'
import { cn } from '../../utils/cn'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'

export default function AuditLogPage() {
  const { t } = useTranslation('admin')
  const { t: tc } = useTranslation('common')
  const [page, setPage] = useState(0)
  // Radix Select forbids an empty-string item value (it reserves '' for the
  // placeholder/clear state and throws on render), so the "all" options use a
  // sentinel that maps back to "no filter".
  const ALL_ACTIONS = 'all'
  const ALL_SOURCES = 'all'
  const [filter, setFilter] = useState('')
  // App vs. holding category split (log.category: 'app' | 'holding').
  const [category, setCategory] = useState('')
  const limit = 20

  const { data, isLoading } = useQuery({
    queryKey: ['audit-logs', page, filter, category],
    queryFn: () =>
      adminService.getAuditLogs(page * limit, limit, filter || undefined, category || undefined),
  })

  const logs = data?.logs || []
  const total = data?.total || 0
  const totalPages = Math.ceil(total / limit)

  const ACTION_COLORS = {
    user_ban: 'text-error',
    user_unban: 'text-success',
    role_change: 'text-warning',
    template_create: 'text-accent',
    template_delete: 'text-warning',
    password_change: 'text-violet',
  }

  const DETAIL_LABELS = {
    reason: t('auditLog.detailKeys.reason'),
    new_role: t('auditLog.detailKeys.newRole'),
    name: t('auditLog.detailKeys.name'),
  }

  const formatDetailValue = (val) => {
    if (val == null || val === '') return '—'
    if (typeof val === 'boolean') return val ? t('auditLog.yes') : t('auditLog.no')
    if (typeof val === 'number') return fmtNumber(val)
    if (Array.isArray(val)) return val.length ? val.map(formatDetailValue).join('، ') : '—'
    if (typeof val === 'object') return Object.keys(val).length ? t('auditLog.detailsObject') : '—'
    return String(val)
  }

  const renderDetails = (details) => {
    if (!details || typeof details !== 'object' || Object.keys(details).length === 0) {
      return <span className="text-foreground-tertiary">—</span>
    }
    return (
      <dl className="flex flex-col gap-0.5">
        {Object.entries(details).map(([key, val]) => (
          <div key={key} className="flex items-baseline gap-1.5">
            <dt className="text-foreground-tertiary">{DETAIL_LABELS[key] || key}:</dt>
            <dd className="text-foreground-secondary break-words">{formatDetailValue(val)}</dd>
          </div>
        ))}
      </dl>
    )
  }

  return (
    <PageShell width="dense">
        <PageHeader
          icon={ScrollText}
          tone="sky"
          title={t('auditLog.title')}
          subtitle={t('auditLog.subtitle')}
          actions={
            <>
              <Filter className="h-4 w-4 text-foreground-secondary" />
              <Select
                value={category || ALL_SOURCES}
                onValueChange={(value) => { setCategory(value === ALL_SOURCES ? '' : value); setPage(0) }}
              >
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder={t('auditLog.allSources', 'All sources')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_SOURCES}>{t('auditLog.allSources', 'All sources')}</SelectItem>
                  <SelectItem value="app">{t('auditLog.sourceApp', 'App')}</SelectItem>
                  <SelectItem value="holding">{t('auditLog.sourceHolding', 'Holding')}</SelectItem>
                </SelectContent>
              </Select>
              <Select
                value={filter || ALL_ACTIONS}
                onValueChange={(value) => { setFilter(value === ALL_ACTIONS ? '' : value); setPage(0) }}
              >
                <SelectTrigger className="w-[200px]">
                  <SelectValue placeholder={t('auditLog.allActions')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_ACTIONS}>{t('auditLog.allActions')}</SelectItem>
                  <SelectItem value="user_ban">{t('auditLog.userBans')}</SelectItem>
                  <SelectItem value="user_unban">{t('auditLog.userUnbans')}</SelectItem>
                  <SelectItem value="role_change">{t('auditLog.roleChanges')}</SelectItem>
                  <SelectItem value="template_create">{t('auditLog.templateCreates')}</SelectItem>
                  <SelectItem value="template_delete">{t('auditLog.templateDeletes')}</SelectItem>
                </SelectContent>
              </Select>
            </>
          }
        />

        <Card>
          <CardContent className="p-0">
            {isLoading ? (
              <div className="p-6 space-y-3">
                {[1,2,3,4,5].map(i => <Skeleton key={i} className="h-12 w-full" />)}
              </div>
            ) : logs.length === 0 ? (
              <p className="text-foreground-secondary text-center py-12">{t('auditLog.noLogs')}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-background-tertiary text-xs uppercase tracking-wide text-foreground-secondary">
                    <tr className="border-b border-border">
                      <th className="text-start py-3 px-4 font-bold">{t('auditLog.colAction')}</th>
                      <th className="text-start py-3 px-4 font-bold">{t('auditLog.colSource', 'Source')}</th>
                      <th className="text-start py-3 px-4 font-bold">{t('auditLog.colAdmin')}</th>
                      <th className="text-start py-3 px-4 font-bold">{t('auditLog.colDetails')}</th>
                      <th className="text-start py-3 px-4 font-bold">{t('auditLog.colIP')}</th>
                      <th className="text-start py-3 px-4 font-bold">{t('auditLog.colTime')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((log) => {
                      const color = ACTION_COLORS[log.action] || 'text-foreground'
                      const label = t(`auditLog.actions.${log.action}`, { defaultValue: log.action })
                      return (
                        <tr key={log._id} className="border-b border-border/50 hover:bg-background-secondary/50">
                          <td className="py-3 px-4"><span className={cn('font-medium', color)}>{label}</span></td>
                          <td className="py-3 px-4">
                            {log.category === 'holding' ? (
                              <Badge variant="secondary" className="bg-accent/15 text-accent border-accent/30">
                                {t('auditLog.sourceHolding', 'Holding')}
                              </Badge>
                            ) : (
                              <Badge variant="secondary">{t('auditLog.sourceApp', 'App')}</Badge>
                            )}
                          </td>
                          <td className="py-3 px-4 text-foreground-secondary">{log.admin_email || t('users.unknown')}</td>
                          <td className="py-3 px-4 text-sm max-w-xs">{renderDetails(log.details)}</td>
                          <td className="py-3 px-4 text-foreground-tertiary text-sm font-mono" dir="ltr">{log.ip_address || '-'}</td>
                          <td className="py-3 px-4 text-foreground-tertiary text-sm whitespace-nowrap">{log.created_at ? fmtDate(new Date(log.created_at), 'PPpp') : '-'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-border">
                <p className="text-sm text-foreground-secondary">
                  {t('auditLog.page', { current: fmtNumber(page + 1), total: fmtNumber(totalPages) })}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => setPage(p => Math.max(0, p - 1))}
                    disabled={page === 0}
                    aria-label={tc('aria.previousPage')}
                  >
                    <ChevronLeft className="h-4 w-4 rtl:rotate-180" />
                  </Button>
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                    disabled={page >= totalPages - 1}
                    aria-label={tc('aria.nextPage')}
                  >
                    <ChevronRight className="h-4 w-4 rtl:rotate-180" />
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
    </PageShell>
  )
}

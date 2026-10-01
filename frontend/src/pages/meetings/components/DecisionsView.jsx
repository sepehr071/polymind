import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, FileText, Gavel } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import EmptyState from '@/components/ui/empty-state'
import PanelHeader from './PanelHeader'
import { getSummary } from '@/services/meetingsService'
import { dirOf } from '@/utils/rtl'
import { fmtNumber } from '@/utils/persianLocale'

function isNotFound(err) {
  if (!err) return false
  const status = err?.response?.status
  if (status === 404) return true
  return err instanceof Error && err.message?.startsWith('404 ')
}

export default function DecisionsView({ meetingId }) {
  const { t } = useTranslation('meetings')
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['summary', meetingId],
    queryFn: () => getSummary(meetingId),
    retry: false,
  })

  if (isLoading) {
    return (
      <>
        <PanelHeader kicker={t('panels.decisions.kicker')} title="…" />
        <div className="space-y-3">
          <div className="h-20 rounded-xl animate-shimmer" />
          <div className="h-20 rounded-xl animate-shimmer" />
        </div>
      </>
    )
  }

  if (isError) {
    if (isNotFound(error)) {
      return (
        <EmptyState icon={FileText} title={t('panels.decisions.notReady')} />
      )
    }
    return (
      <EmptyState
        icon={AlertTriangle}
        title={t('panels.decisions.error')}
        tone="destructive"
      />
    )
  }

  if (!data) return null
  const decisions = data.decisions ?? []

  if (decisions.length === 0) {
    return (
      <>
        <PanelHeader
          kicker={t('panels.decisions.kicker')}
          title={t('panels.decisions.empty')}
        />
        <EmptyState
          icon={Gavel}
          title={t('panels.decisions.empty')}
          hint={t('panels.decisions.emptyHint')}
        />
      </>
    )
  }

  return (
    <>
      <PanelHeader
        kicker={t('panels.decisions.kicker')}
        title={t('panels.decisions.title', { count: decisions.length })}
      />
      <div className="flex flex-col gap-3.5">
        {decisions.map((d, i) => (
          <article
            key={i}
            className="grid grid-cols-[32px_1fr] gap-4 rounded-2xl border border-border bg-background-elevated px-6 py-5"
          >
            <span className="grid size-7 place-items-center rounded-full bg-amber-500/15 text-xs font-bold text-amber-700 font-mono tabular-nums dark:bg-amber-400/15 dark:text-amber-300">
              {fmtNumber(i + 1)}
            </span>
            <p
              dir={dirOf(d)}
              className="text-base font-medium leading-7 tracking-tight text-foreground"
            >
              {d}
            </p>
          </article>
        ))}
      </div>
    </>
  )
}

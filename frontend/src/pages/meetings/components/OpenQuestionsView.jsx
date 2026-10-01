import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, FileText, HelpCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import EmptyState from '@/components/ui/empty-state'
import PanelHeader from './PanelHeader'
import { getSummary } from '@/services/meetingsService'
import { dirOf } from '@/utils/rtl'

function isNotFound(err) {
  if (!err) return false
  const status = err?.response?.status
  if (status === 404) return true
  return err instanceof Error && err.message?.startsWith('404 ')
}

export default function OpenQuestionsView({ meetingId }) {
  const { t } = useTranslation('meetings')
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['summary', meetingId],
    queryFn: () => getSummary(meetingId),
    retry: false,
  })

  if (isLoading) {
    return (
      <>
        <PanelHeader kicker={t('panels.open.kicker')} title="…" />
        <div className="h-20 rounded-xl animate-shimmer" />
      </>
    )
  }

  if (isError) {
    if (isNotFound(error)) {
      return <EmptyState icon={FileText} title={t('panels.open.notReady')} />
    }
    return (
      <EmptyState
        icon={AlertTriangle}
        title={t('panels.open.error')}
        tone="destructive"
      />
    )
  }

  const items = data?.open_questions ?? []
  if (items.length === 0) {
    return (
      <>
        <PanelHeader
          kicker={t('panels.open.kicker')}
          title={t('panels.open.empty')}
        />
        <EmptyState
          icon={HelpCircle}
          title={t('panels.open.empty')}
          hint={t('panels.open.emptyHint')}
        />
      </>
    )
  }

  return (
    <>
      <PanelHeader
        kicker={t('panels.open.kicker')}
        title={t('panels.open.title')}
      />
      <div className="flex flex-col gap-2.5">
        {items.map((q, i) => (
          <article
            key={i}
            className="flex items-start gap-3 rounded-xl border border-border bg-background-elevated px-5 py-3.5"
          >
            <span className="grid size-6 shrink-0 place-items-center rounded-md bg-warning/10 text-warning">
              <AlertTriangle className="size-3.5" />
            </span>
            <p
              dir={dirOf(q.question ?? '')}
              className="flex-1 text-sm leading-7 text-foreground"
            >
              {q.question}
            </p>
            {q.owner && (
              <span
                dir={dirOf(q.owner)}
                className="shrink-0 rounded-full bg-background-tertiary px-2.5 py-0.5 text-[11px] text-foreground-secondary"
              >
                {q.owner}
              </span>
            )}
          </article>
        ))}
      </div>
    </>
  )
}

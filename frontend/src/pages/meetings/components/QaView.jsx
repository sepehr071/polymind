import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, FileText, MessagesSquare, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import EmptyState from '@/components/ui/empty-state'
import { IconTile } from '@/components/ui/icon-tile'
import PanelHeader from './PanelHeader'
import { getSummary } from '@/services/meetingsService'
import { dirOf } from '@/utils/rtl'

function isNotFound(err) {
  if (!err) return false
  const status = err?.response?.status
  if (status === 404) return true
  return err instanceof Error && err.message?.startsWith('404 ')
}

export default function QaView({ meetingId }) {
  const { t } = useTranslation('meetings')
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['summary', meetingId],
    queryFn: () => getSummary(meetingId),
    retry: false,
  })

  if (isLoading) {
    return (
      <>
        <PanelHeader kicker={t('panels.qa.kicker')} title="…" />
        <div className="space-y-3">
          <div className="h-24 rounded-xl animate-shimmer" />
          <div className="h-24 rounded-xl animate-shimmer" />
        </div>
      </>
    )
  }

  if (isError) {
    if (isNotFound(error)) {
      return <EmptyState icon={FileText} title={t('panels.qa.notReady')} />
    }
    return (
      <EmptyState
        icon={AlertTriangle}
        title={t('panels.qa.error')}
        tone="destructive"
      />
    )
  }

  const items = data?.qa ?? []
  if (items.length === 0) {
    return (
      <>
        <PanelHeader kicker={t('panels.qa.kicker')} title={t('panels.qa.empty')} />
        <EmptyState
          icon={MessagesSquare}
          title={t('panels.qa.empty')}
          hint={t('panels.qa.emptyHint')}
        />
      </>
    )
  }

  return (
    <>
      <PanelHeader
        kicker={t('panels.qa.kicker')}
        title={t('panels.qa.title', { count: items.length })}
      />
      <div className="flex flex-col gap-3">
        {items.map((qa, i) => (
          <article
            key={i}
            className="overflow-hidden rounded-2xl border border-border bg-background-elevated"
          >
            <div className="px-6 pb-2.5 pt-5">
              <p
                dir={dirOf(qa.question ?? '')}
                className="text-sm font-semibold leading-7 text-foreground"
              >
                {qa.question}
              </p>
            </div>
            <div className="border-t border-dashed border-border-light px-6 pb-5 pt-4">
              {qa.answer ? (
                <div className="flex gap-3">
                  <IconTile icon={Sparkles} tone="amber" size="md" className="mt-0.5" />
                  <p
                    dir={dirOf(qa.answer)}
                    className="text-sm leading-7 text-foreground-secondary"
                  >
                    {qa.answer}
                  </p>
                </div>
              ) : (
                <p className="italic text-sm text-foreground-tertiary">
                  {t('panels.qa.unanswered')}
                </p>
              )}
            </div>
          </article>
        ))}
      </div>
    </>
  )
}

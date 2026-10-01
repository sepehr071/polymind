import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, FileText, ScrollText } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import EmptyState from '@/components/ui/empty-state'
import PanelHeader from './PanelHeader'
import { getTranscript } from '@/services/meetingsService'
import { dirOf } from '@/utils/rtl'

function isNotFound(err) {
  if (!err) return false
  const status = err?.response?.status
  if (status === 404) return true
  return err instanceof Error && err.message?.startsWith('404 ')
}

export default function TranscriptView({ meetingId }) {
  const { t } = useTranslation('meetings')
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['transcript', meetingId],
    queryFn: () => getTranscript(meetingId),
    retry: false,
  })

  if (isLoading) {
    return (
      <>
        <PanelHeader kicker={t('panels.transcript.kicker')} title="…" />
        <div className="space-y-2">
          <div className="h-5 w-full rounded animate-shimmer" />
          <div className="h-5 w-5/6 rounded animate-shimmer" />
          <div className="h-5 w-4/5 rounded animate-shimmer" />
          <div className="h-5 w-3/5 rounded animate-shimmer" />
        </div>
      </>
    )
  }

  if (isError) {
    if (isNotFound(error)) {
      return (
        <EmptyState icon={FileText} title={t('panels.transcript.notReady')} />
      )
    }
    return (
      <EmptyState
        icon={AlertTriangle}
        title={t('panels.transcript.error')}
        tone="destructive"
      />
    )
  }

  if (!data) return null
  if (!data.plain_text?.trim()) {
    return <EmptyState icon={ScrollText} title={t('panels.transcript.empty')} />
  }

  const wordCount = data.plain_text.trim().split(/\s+/).length

  return (
    <>
      <PanelHeader
        kicker={t('panels.transcript.kicker')}
        title={t('panels.transcript.title')}
        subtitle={t('panels.transcript.wordCount', { count: wordCount })}
      />
      <div className="rounded-2xl border border-border bg-card p-6 shadow-card">
        <pre
          dir={dirOf(data.plain_text)}
          className="whitespace-pre-wrap break-words font-sans text-[14px] leading-[2.1] text-foreground"
        >
          {data.plain_text}
        </pre>
      </div>
    </>
  )
}

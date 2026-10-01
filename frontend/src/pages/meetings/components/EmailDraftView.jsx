import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Copy, FileText, Mail } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import EmptyState from '@/components/ui/empty-state'
import PanelHeader from './PanelHeader'
import { getMeeting, getSummary } from '@/services/meetingsService'
import { dirOf } from '@/utils/rtl'

function isNotFound(err) {
  if (!err) return false
  const status = err?.response?.status
  if (status === 404) return true
  return err instanceof Error && err.message?.startsWith('404 ')
}

export default function EmailDraftView({ meetingId }) {
  const { t } = useTranslation('meetings')
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['summary', meetingId],
    queryFn: () => getSummary(meetingId),
    retry: false,
  })
  const meetingQ = useQuery({
    queryKey: ['meeting', meetingId],
    queryFn: () => getMeeting(meetingId),
  })

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('panels.email.copied'))
    } catch {
      toast.error(t('panels.email.copyFailed'))
    }
  }

  if (isLoading) {
    return (
      <>
        <PanelHeader kicker={t('panels.email.kicker')} title="…" />
        <div className="space-y-2">
          <div className="h-8 rounded animate-shimmer" />
          <div className="h-32 rounded animate-shimmer" />
        </div>
      </>
    )
  }

  if (isError) {
    if (isNotFound(error)) {
      return <EmptyState icon={FileText} title={t('panels.email.notReady')} />
    }
    return (
      <EmptyState
        icon={AlertTriangle}
        title={t('panels.email.error')}
        tone="destructive"
      />
    )
  }

  const email = data?.email
  const subject = email?.subject ?? data?.email_subject
  const body = email?.body ?? data?.email_draft
  const tone = email?.tone ?? data?.email_tone

  if (!subject && !body) {
    return (
      <>
        <PanelHeader
          kicker={t('panels.email.kicker')}
          title={t('panels.email.empty')}
        />
        <EmptyState
          icon={Mail}
          title={t('panels.email.empty')}
          hint={t('panels.email.emptyHint')}
        />
      </>
    )
  }

  const fullEmail = `${subject ?? ''}\n\n${body ?? ''}`.trim()
  const toneLabel =
    tone === 'casual' ? t('panels.email.toneCasual') : t('panels.email.toneFormal')
  const seriesName = meetingQ.data?.series?.name
  const subtitle = seriesName
    ? t('panels.email.rewritten', { name: seriesName, tone: toneLabel })
    : t('panels.email.tone', { tone: toneLabel })

  return (
    <>
      <PanelHeader
        kicker={t('panels.email.kicker')}
        title={t('panels.email.title')}
        subtitle={subtitle}
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => copy(fullEmail)}
            className="gap-1.5 border-border"
          >
            <Copy className="size-3.5" />
            {t('panels.email.copy')}
          </Button>
        }
      />

      <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-card">
        {subject && (
          <div className="border-b border-border px-6 py-4">
            <p className="mb-1 text-[11px] font-medium uppercase tracking-wider text-foreground-tertiary">
              {t('panels.email.subject')}
            </p>
            <p
              dir={dirOf(subject)}
              className="text-sm font-semibold leading-7 text-foreground"
            >
              {subject}
            </p>
          </div>
        )}
        {body && (
          <div className="px-6 py-5">
            <pre
              dir={dirOf(body)}
              className="whitespace-pre-wrap break-words font-sans text-sm leading-[2] text-foreground-secondary"
            >
              {body}
            </pre>
          </div>
        )}
      </div>
    </>
  )
}

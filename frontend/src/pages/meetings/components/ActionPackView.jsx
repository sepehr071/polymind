import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Loader2, Package } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import EmptyState from '@/components/ui/empty-state'
import PanelHeader from './PanelHeader'
import { useBudgetBlock } from '@/hooks/useBudgetBlock'
import { useDlpConfirm } from '@/hooks/useDlpConfirm'
import { useWorkspace } from '@/context/WorkspaceContext'
import {
  generateActionPack,
  getMeeting,
  getSummary,
  getTranscript,
} from '@/services/meetingsService'
import { meetingActionPackScanText } from '@/utils/studioDlpText'

function packToMarkdown(pack, t) {
  if (!pack) return ''
  const lines = [
    `# ${t('panels.pack.title')}`,
    '',
    `## ${t('panels.pack.actions')}`,
    ...(pack.action_items || []).map(
      (a) => `- ${a.task}${a.owner ? ` (@${a.owner})` : ''}${a.due ? ` — ${a.due}` : ''}`,
    ),
    '',
    `## ${t('panels.pack.decisions')}`,
    ...(pack.decisions || []).map((d) => `- ${d.decision}${d.context ? `: ${d.context}` : ''}`),
    '',
    `## ${t('panels.pack.email')}`,
    pack.email?.subject ? `**${pack.email.subject}**` : '',
    pack.email?.body || '',
    '',
    `## ${t('panels.pack.memo')}`,
    pack.memo || '',
  ]
  return lines.filter(Boolean).join('\n')
}

export default function ActionPackView({ meetingId, meetingReady }) {
  const { t, i18n } = useTranslation('meetings')
  const queryClient = useQueryClient()
  const { currentWorkspace } = useWorkspace()
  const [pack, setPack] = useState(null)
  const { handleBudgetError, budgetModal } = useBudgetBlock()
  const { scan, dlpModal } = useDlpConfirm({ source: 'meeting' })

  const summaryQ = useQuery({
    queryKey: ['summary', meetingId],
    queryFn: () => getSummary(meetingId),
    enabled: meetingReady,
    retry: false,
  })

  const mut = useMutation({
    mutationFn: async () => {
      const lang = (i18n.language || 'fa').startsWith('en') ? 'en' : 'fa'
      // Build the same seed body BE gates (build_seed_text) so confirm_token matches.
      const [meeting, transcript, summary] = await Promise.all([
        getMeeting(meetingId),
        getTranscript(meetingId).catch(() => null),
        getSummary(meetingId).catch(() => null),
      ])
      const scanText = meetingActionPackScanText(meeting, transcript, summary)
      const dlp = await scan(scanText)
      if (dlp === null) throw new Error('dlp_cancelled')
      return generateActionPack(meetingId, {
        lang,
        workspace_id: currentWorkspace?._id || null,
        dlp_confirmed: !!dlp?.confirmed,
        dlp_confirm_token: dlp?.confirm_token || undefined,
        dlp_redact: dlp?.redact || undefined,
      })
    },
    onSuccess: (data) => {
      setPack(data)
      queryClient.invalidateQueries({ queryKey: ['summary', meetingId] })
      toast.success(t('panels.pack.done'))
    },
    onError: (err) => {
      if (err?.message === 'dlp_cancelled') return
      const body = err?.response?.data
      if (handleBudgetError?.(body || err)) return
      // Gate may mint confirm_token on 403; surface message (modal already covered preflight).
      toast.error(body?.error || body?.message || err?.message || t('panels.pack.failed'))
    },
  })

  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text || '')
      toast.success(t('panels.pack.copied'))
    } catch {
      toast.error(t('panels.pack.failed'))
    }
  }

  if (!meetingReady) {
    return <EmptyState icon={Package} title={t('panels.pack.notReady')} />
  }

  const display = pack || {
    action_items: summaryQ.data?.action_items,
    decisions: summaryQ.data?.decisions,
    email: {
      body: summaryQ.data?.email_draft,
      subject: '',
      tone: summaryQ.data?.email_tone || summaryQ.data?.tone,
    },
    memo: summaryQ.data?.memo,
  }

  return (
    <div className="space-y-4 p-1">
      <PanelHeader
        kicker={t('panels.pack.kicker')}
        title={t('panels.pack.title')}
        subtitle={t('panels.pack.subtitle')}
      />
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => mut.mutate()} disabled={mut.isPending}>
          {mut.isPending ? <Loader2 className="h-4 w-4 animate-spin me-2" /> : <Package className="h-4 w-4 me-2" />}
          {t('panels.pack.generate')}
        </Button>
        <Button type="button" variant="outline" onClick={() => copy(packToMarkdown(display, t))} disabled={!display?.memo && !display?.email?.body}>
          <Copy className="h-4 w-4 me-2" />
          {t('panels.pack.copyAll')}
        </Button>
      </div>
      {!!display?.action_items?.length && (
        <section className="space-y-1">
          <h3 className="text-sm font-semibold">{t('panels.pack.actions')}</h3>
          <ul className="list-disc ps-5 text-sm space-y-1" dir="auto">
            {display.action_items.map((a, i) => (
              <li key={i}>{a.task || a.text}{a.owner ? ` — ${a.owner}` : ''}</li>
            ))}
          </ul>
        </section>
      )}
      {!!display?.decisions?.length && (
        <section className="space-y-1">
          <h3 className="text-sm font-semibold">{t('panels.pack.decisions')}</h3>
          <ul className="list-disc ps-5 text-sm space-y-1" dir="auto">
            {display.decisions.map((d, i) => (
              <li key={i}>{typeof d === 'string' ? d : d.decision}</li>
            ))}
          </ul>
        </section>
      )}
      {(display?.email?.body || display?.email?.subject) && (
        <section className="space-y-1">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">{t('panels.pack.email')}</h3>
            <Button type="button" size="sm" variant="ghost" onClick={() => copy(`${display.email.subject || ''}\n\n${display.email.body || ''}`)}>
              <Copy className="h-3.5 w-3.5" />
            </Button>
          </div>
          {display.email.subject && <p className="text-sm font-medium" dir="auto">{display.email.subject}</p>}
          <pre className="whitespace-pre-wrap text-sm font-sans rounded-lg border border-border/40 p-3" dir="auto">{display.email.body}</pre>
        </section>
      )}
      {display?.memo && (
        <section className="space-y-1">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">{t('panels.pack.memo')}</h3>
            <Button type="button" size="sm" variant="ghost" onClick={() => copy(display.memo)}>
              <Copy className="h-3.5 w-3.5" />
            </Button>
          </div>
          <pre className="whitespace-pre-wrap text-sm font-sans rounded-lg border border-border/40 p-3" dir="auto">{display.memo}</pre>
        </section>
      )}
      {budgetModal}
      {dlpModal}
    </div>
  )
}

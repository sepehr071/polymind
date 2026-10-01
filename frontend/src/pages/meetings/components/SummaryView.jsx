import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckSquare,
  AlertCircle,
  FileText,
  Gavel,
  Sparkles,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import EmptyState from '@/components/ui/empty-state'
import { IconTile } from '@/components/ui/icon-tile'
import PanelHeader from './PanelHeader'
import { getSummary } from '@/services/meetingsService'
import { formatJalali } from '@/utils/rtl'
import { fmtNumber } from '@/utils/persianLocale'
import { prettifyModelName } from '@/utils/modelName'

function isNotFound(err) {
  if (!err) return false
  const status = err?.response?.status
  if (status === 404) return true
  return err instanceof Error && err.message?.startsWith('404 ')
}

const HEADLINE_MAX = 120

// Clamp to `max` chars on a word boundary (never mid-word), appending an
// ellipsis when the text was actually truncated.
function clampWords(text, max = HEADLINE_MAX) {
  const s = text.trim()
  if (s.length <= max) return s
  const cut = s.slice(0, max)
  const lastSpace = cut.lastIndexOf(' ')
  const head = lastSpace > max * 0.5 ? cut.slice(0, lastSpace) : cut
  return `${head.trimEnd()}…`
}

function deriveHeadline(text) {
  const s = text.trim()
  // A complete first sentence is the ideal headline; fall back to a
  // word-boundary clamp so we never cut mid-word.
  const m = s.match(/^[^.!?؟]+[.!?؟]?/)
  const sentence = m?.[0]?.trim()
  if (sentence && sentence.length >= 6 && sentence.length <= HEADLINE_MAX) {
    return sentence
  }
  return clampWords(s)
}

function InsightTile({ icon, tone, value, label, sub }) {
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-5 shadow-card">
      <IconTile icon={icon} tone={tone} size="lg" />
      <div>
        <div className="text-[24px] font-extrabold leading-none tracking-[-0.01em] text-foreground tabular-nums">
          {typeof value === 'number' ? fmtNumber(value) : value}
        </div>
        <div className="mt-1.5 text-xs text-foreground-tertiary">{label}</div>
        {sub && (
          <div className="mt-0.5 text-xs text-foreground-tertiary">
            {sub}
          </div>
        )}
      </div>
    </div>
  )
}

export default function SummaryView({ meetingId }) {
  const { t } = useTranslation('meetings')
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['summary', meetingId],
    queryFn: () => getSummary(meetingId),
    retry: false,
  })

  if (isLoading) {
    return (
      <>
        <PanelHeader kicker={t('panels.summary.kicker')} title="…" />
        <div className="space-y-2">
          <div className="h-7 w-3/4 rounded animate-shimmer" />
          <div className="h-7 w-full rounded animate-shimmer" />
          <div className="h-7 w-5/6 rounded animate-shimmer" />
        </div>
      </>
    )
  }

  if (isError) {
    if (isNotFound(error)) {
      return (
        <EmptyState
          icon={FileText}
          title={t('panels.summary.notReady')}
          hint={t('panels.summary.notReadyHint')}
        />
      )
    }
    return (
      <EmptyState
        icon={AlertTriangle}
        title={t('panels.summary.error')}
        tone="destructive"
      />
    )
  }

  if (!data) return null

  const exec = (data.exec_summary ?? '').trim()
  // Prefer an explicit headline/title field if the summary ever ships one;
  // otherwise derive a clean (word-boundary) headline from the exec summary.
  const explicitHeadline = (data.headline ?? data.title ?? '').trim()
  const headline = explicitHeadline
    ? clampWords(explicitHeadline)
    : exec
      ? deriveHeadline(exec)
      : t('panels.summary.fallbackTitle')

  const actionItems = data.action_items ?? []
  const decisions = data.decisions ?? []
  const openQuestions = data.open_questions ?? []
  const datedActions = actionItems.filter((a) => a?.due_date).length

  return (
    <>
      <PanelHeader kicker={t('panels.summary.kicker')} title={headline} />

      <div className="mb-6 flex items-center gap-2 text-xs text-foreground-secondary">
        <IconTile icon={Sparkles} tone="amber" size="sm" />
        <span>{t('panels.summary.generatedBy')}</span>
        <span className="text-foreground-tertiary">
          {prettifyModelName(data.model)}
        </span>
        <span>·</span>
        <span>{formatJalali(data.created_at)}</span>
      </div>

      <div className="mb-7 rounded-2xl border border-border bg-card p-6 shadow-card">
        {exec ? (
          <p className="whitespace-pre-wrap text-[14px] leading-[2.1] text-foreground">
            {exec}
          </p>
        ) : (
          <p className="text-sm text-foreground-tertiary">
            {t('panels.summary.noSummary')}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <InsightTile
          icon={CheckSquare}
          tone="emerald"
          value={actionItems.length}
          label={t('panels.summary.actionItemsTile')}
          sub={
            actionItems.length > 0
              ? t('panels.summary.actionItemsSub', { count: datedActions })
              : undefined
          }
        />
        <InsightTile
          icon={Gavel}
          tone="amber"
          value={decisions.length}
          label={t('panels.summary.decisionsTile')}
        />
        <InsightTile
          icon={AlertCircle}
          tone="rose"
          value={openQuestions.length}
          label={t('panels.summary.openQuestionsTile')}
          sub={
            openQuestions.length > 0
              ? t('panels.summary.openQuestionsSub')
              : undefined
          }
        />
      </div>
    </>
  )
}

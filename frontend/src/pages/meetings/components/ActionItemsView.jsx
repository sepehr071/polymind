import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CalendarDays, FileText, ListChecks } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import EmptyState from '@/components/ui/empty-state'
import PanelHeader from './PanelHeader'
import { getSummary } from '@/services/meetingsService'
import { cn } from '@/utils/cn'
import { dirOf, formatJalali } from '@/utils/rtl'
import { fmtNumber } from '@/utils/persianLocale'

function isNotFound(err) {
  if (!err) return false
  const status = err?.response?.status
  if (status === 404) return true
  return err instanceof Error && err.message?.startsWith('404 ')
}

export default function ActionItemsView({ meetingId }) {
  const { t } = useTranslation('meetings')
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['summary', meetingId],
    queryFn: () => getSummary(meetingId),
    retry: false,
  })
  const [done, setDone] = useState(() => new Set())

  const grouped = useMemo(() => {
    if (!data) return new Map()
    const m = new Map()
    ;(data.action_items ?? []).forEach((item, idx) => {
      const key = item?.owner?.trim() || t('panels.actions.unassigned')
      if (!m.has(key)) m.set(key, [])
      m.get(key).push({ idx, item })
    })
    return m
  }, [data, t])

  if (isLoading) {
    return (
      <>
        <PanelHeader kicker={t('panels.actions.kicker')} title="…" />
        <div className="space-y-2">
          <div className="h-16 rounded-xl animate-shimmer" />
          <div className="h-16 rounded-xl animate-shimmer" />
        </div>
      </>
    )
  }

  if (isError) {
    if (isNotFound(error)) {
      return (
        <EmptyState
          icon={FileText}
          title={t('panels.actions.notReady')}
          hint={t('panels.actions.notReadyHint')}
        />
      )
    }
    return (
      <EmptyState
        icon={AlertTriangle}
        title={t('panels.actions.error')}
        tone="destructive"
      />
    )
  }

  if (!data) return null
  const total = (data.action_items ?? []).length

  if (total === 0) {
    return (
      <>
        <PanelHeader
          kicker={t('panels.actions.kicker')}
          title={t('panels.actions.empty')}
        />
        <EmptyState
          icon={ListChecks}
          title={t('panels.actions.empty')}
          hint={t('panels.actions.emptyHint')}
        />
      </>
    )
  }

  function toggle(idx) {
    setDone((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  return (
    <>
      <PanelHeader
        kicker={t('panels.actions.kicker')}
        title={t('panels.actions.headerTitle', { count: total })}
        subtitle={t('panels.actions.headerSubtitle', {
          done: done.size,
          total,
          remaining: total - done.size,
        })}
      />

      <p className="mb-4 text-xs text-foreground-tertiary" aria-live="polite">
        {t('panels.actions.viewOnlyNote')}
      </p>

      <div className="space-y-6">
        {Array.from(grouped.entries()).map(([owner, items]) => (
          <div key={owner}>
            <div className="mb-2.5 flex items-center gap-2">
              <span
                className="grid size-5 place-items-center rounded-full bg-accent/10 text-[10px] font-semibold text-accent"
                aria-hidden="true"
              >
                {owner[0]}
              </span>
              <h3
                dir={dirOf(owner)}
                className="text-xs font-semibold tracking-wide text-foreground-secondary"
              >
                {owner} · {fmtNumber(items.length)}
              </h3>
            </div>
            <div className="overflow-hidden rounded-xl border border-border bg-background-elevated">
              {items.map(({ idx, item }, i) => {
                const isDone = done.has(idx)
                return (
                  <div
                    key={idx}
                    className={cn(
                      'flex items-start gap-3 px-5 py-3.5 transition-opacity',
                      i < items.length - 1 && 'border-b border-border-light',
                      isDone && 'opacity-55'
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => toggle(idx)}
                      aria-label={
                        isDone
                          ? t('panels.actions.markUndone')
                          : t('panels.actions.markDone')
                      }
                      className={cn(
                        'mt-0.5 grid size-[18px] shrink-0 place-items-center rounded-md border transition-colors',
                        isDone
                          ? 'border-success bg-success text-white'
                          : 'border-border-light bg-background-elevated text-foreground-tertiary hover:border-foreground-tertiary'
                      )}
                    >
                      {isDone && (
                        <svg
                          viewBox="0 0 12 12"
                          className="size-2.5"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M2.5 6.5l2.5 2.5 4.5-5" />
                        </svg>
                      )}
                    </button>
                    <div className="flex-1">
                      <p
                        dir={dirOf(item.text ?? '')}
                        className={cn(
                          'text-sm font-medium leading-7 text-foreground',
                          isDone && 'line-through'
                        )}
                      >
                        {item.text}
                      </p>
                      {item.due_date && (
                        <div className="mt-2 flex items-center gap-1.5 text-xs text-foreground-secondary">
                          <CalendarDays className="size-3" />
                          <span className="font-mono tabular-nums">
                            {formatJalali(item.due_date)}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

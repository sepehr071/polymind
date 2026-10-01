import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  FileText,
  ListTree,
  Pencil,
  Search,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import EmptyState from '@/components/ui/empty-state'
import PanelHeader from './PanelHeader'
import { getMeeting, getSummary, renameSpeaker } from '@/services/meetingsService'
import { listSeriesSpeakerNames } from '@/services/meetingSeriesService'
import { cn } from '@/utils/cn'
import { dirOf } from '@/utils/rtl'

// Speaker chip colors are themeable CSS vars (`--speaker-1..6`, defined in
// index.css for :root + .dark). Inline `style` consumers must wrap the triplet
// in hsl(var(...)) — a bare var() resolves to an invalid color.
const SPEAKER_COLORS = [
  'hsl(var(--speaker-1))',
  'hsl(var(--speaker-2))',
  'hsl(var(--speaker-3))',
  'hsl(var(--speaker-4))',
  'hsl(var(--speaker-5))',
  'hsl(var(--speaker-6))',
]

function isNotFound(err) {
  if (!err) return false
  const status = err?.response?.status
  if (status === 404) return true
  return err instanceof Error && err.message?.startsWith('404 ')
}

function formatTime(seconds) {
  const total = Math.max(0, Math.round(seconds))
  const mm = Math.floor(total / 60).toString().padStart(2, '0')
  const ss = (total % 60).toString().padStart(2, '0')
  return `${mm}:${ss}`
}

function colorFor(speakerId, allIds) {
  const i = allIds.indexOf(speakerId)
  return SPEAKER_COLORS[(i < 0 ? 0 : i) % SPEAKER_COLORS.length]
}

function SpeakerChip({ meetingId, speakerId, alias, seriesId, color }) {
  const { t } = useTranslation('meetings')
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(alias ?? '')

  const knownNamesQ = useQuery({
    queryKey: ['speaker-names', seriesId],
    queryFn: () => listSeriesSpeakerNames(seriesId),
    enabled: open && !!seriesId,
  })

  const renameMut = useMutation({
    mutationFn: (name) => renameSpeaker(meetingId, speakerId, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
      queryClient.invalidateQueries({ queryKey: ['summary', meetingId] })
      if (seriesId) {
        queryClient.invalidateQueries({ queryKey: ['speaker-names', seriesId] })
        queryClient.invalidateQueries({ queryKey: ['keyterms', seriesId] })
      }
      toast.success(t('panels.minutes.speakerSaved'))
      setOpen(false)
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : 'error'
      toast.error(`${t('panels.minutes.speakerSaveFailed')}: ${message}`)
    },
  })

  const display = alias ?? speakerId
  const initial = display[0] ?? '?'

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) setDraft(alias ?? '')
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          className="group inline-flex shrink-0 items-center gap-1.5 rounded-full bg-background-tertiary px-2 py-0.5 text-xs font-medium text-foreground-secondary transition-colors hover:bg-background-elevated"
        >
          <span
            className="grid size-5 place-items-center rounded-full text-[10px] font-bold text-white"
            style={{ background: color }}
            aria-hidden="true"
          >
            {initial}
          </span>
          <span dir={dirOf(display)}>{display}</span>
          <Pencil className="size-2.5 text-foreground-tertiary opacity-0 transition-opacity group-hover:opacity-100" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64">
        <div className="space-y-2">
          <label className="text-xs font-medium text-foreground-secondary">
            {t('panels.minutes.speakerLabel')}
          </label>
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={speakerId}
            disabled={renameMut.isPending}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && draft.trim()) {
                renameMut.mutate(draft.trim())
              }
            }}
          />
          {seriesId && (knownNamesQ.data ?? []).length > 0 && (
            <div className="space-y-1">
              <p className="text-xs text-foreground-secondary">
                {t('panels.minutes.speakerFromSeries')}
              </p>
              <div className="flex flex-wrap gap-1">
                {(knownNamesQ.data ?? []).map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="rounded-full border border-border px-2 py-0.5 text-[11px] text-foreground-secondary hover:border-amber-500 hover:text-amber-700 dark:hover:border-amber-400 dark:hover:text-amber-300"
                    onClick={() => setDraft(name)}
                    dir={dirOf(name)}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={() => {
                if (draft.trim()) renameMut.mutate(draft.trim())
              }}
              disabled={renameMut.isPending || !draft.trim()}
            >
              {t('panels.minutes.speakerSave')}
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

export default function MinutesView({ meetingId }) {
  const { t } = useTranslation('meetings')
  const summaryQ = useQuery({
    queryKey: ['summary', meetingId],
    queryFn: () => getSummary(meetingId),
    retry: false,
  })
  const meetingQ = useQuery({
    queryKey: ['meeting', meetingId],
    queryFn: () => getMeeting(meetingId),
  })

  const [query, setQuery] = useState('')
  const [activeSpeakers, setActiveSpeakers] = useState(() => new Set())

  const aliasMap = useMemo(() => {
    const map = {}
    for (const sp of meetingQ.data?.speakers ?? []) {
      map[sp.speaker_id] = sp.display_name ?? null
    }
    for (const [id, info] of Object.entries(summaryQ.data?.speakers ?? {})) {
      if (!(id in map)) map[id] = info?.display_name ?? null
    }
    return map
  }, [meetingQ.data?.speakers, summaryQ.data?.speakers])

  const speakerIds = useMemo(() => {
    const set = new Set()
    for (const seg of summaryQ.data?.minutes ?? []) set.add(seg.speaker_id)
    for (const id of Object.keys(aliasMap)) set.add(id)
    return Array.from(set).sort()
  }, [summaryQ.data?.minutes, aliasMap])

  const filtered = useMemo(() => {
    const segments = summaryQ.data?.minutes ?? []
    const q = query.trim().toLowerCase()
    return segments.filter((seg) => {
      if (activeSpeakers.size > 0 && !activeSpeakers.has(seg.speaker_id)) {
        return false
      }
      if (q && !(seg.text ?? '').toLowerCase().includes(q)) return false
      return true
    })
  }, [summaryQ.data?.minutes, query, activeSpeakers])

  if (summaryQ.isLoading || meetingQ.isLoading) {
    return (
      <>
        <PanelHeader kicker={t('panels.minutes.kicker')} title="…" />
        <div className="space-y-2">
          <div className="h-14 rounded animate-shimmer" />
          <div className="h-14 rounded animate-shimmer" />
        </div>
      </>
    )
  }

  if (summaryQ.isError) {
    if (isNotFound(summaryQ.error)) {
      return <EmptyState icon={FileText} title={t('panels.minutes.notReady')} />
    }
    return (
      <EmptyState
        icon={AlertTriangle}
        title={t('panels.minutes.error')}
        tone="destructive"
      />
    )
  }

  if (!summaryQ.data) return null
  const minutes = summaryQ.data.minutes ?? []

  if (minutes.length === 0) {
    return (
      <>
        <PanelHeader
          kicker={t('panels.minutes.kicker')}
          title={t('panels.minutes.empty')}
        />
        <EmptyState
          icon={ListTree}
          title={t('panels.minutes.empty')}
          hint={t('panels.minutes.emptyHint')}
        />
      </>
    )
  }

  const total = minutes.length
  const filtersActive = query.trim().length > 0 || activeSpeakers.size > 0

  function toggleSpeaker(id) {
    setActiveSpeakers((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function clearFilters() {
    setQuery('')
    setActiveSpeakers(new Set())
  }

  const seriesId = meetingQ.data?.series_id ?? null

  return (
    <>
      <PanelHeader
        kicker={t('panels.minutes.kicker')}
        title={t('panels.minutes.title')}
        subtitle={t('panels.minutes.sections', { count: total })}
      />

      <div className="sticky top-0 z-10 mb-4 space-y-2 rounded-[14px] border border-border bg-background-secondary p-3 shadow-card">
        <div className="relative">
          <Search className="pointer-events-none absolute end-3 top-1/2 size-4 -translate-y-1/2 text-foreground-tertiary" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('panels.minutes.searchPlaceholder')}
            className="pe-9"
          />
        </div>
        {speakerIds.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            {speakerIds.map((id) => {
              const name = aliasMap[id] ?? id
              const active = activeSpeakers.has(id)
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => toggleSpeaker(id)}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition-colors',
                    active
                      ? 'border-transparent bg-amber-500/10 font-semibold text-amber-700 dark:bg-amber-400/10 dark:text-amber-300'
                      : 'border-border bg-background-secondary text-foreground-secondary hover:bg-background-tertiary'
                  )}
                  dir={dirOf(name)}
                >
                  <span
                    className="size-1.5 rounded-full"
                    style={{ background: colorFor(id, speakerIds) }}
                  />
                  {name}
                </button>
              )
            })}
          </div>
        )}
        <div className="flex items-center justify-between text-xs text-foreground-tertiary">
          <span>
            {filtersActive
              ? t('panels.minutes.filtered', {
                  filtered: filtered.length,
                  total,
                })
              : t('panels.minutes.totalSections', { count: total })}
          </span>
          {filtersActive && (
            <button
              type="button"
              onClick={clearFilters}
              className="inline-flex items-center gap-1 text-amber-700 hover:underline dark:text-amber-300"
            >
              <X className="size-3" />
              {t('panels.minutes.clearFilters')}
            </button>
          )}
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={Search}
          title={t('panels.minutes.noMatch')}
          hint={t('panels.minutes.noMatchHint')}
        />
      ) : (
        <div className="space-y-2">
          {filtered.map((segment, idx) => (
            <article
              key={`${segment.speaker_id}-${segment.start_s}-${idx}`}
              className="flex items-start gap-3 rounded-xl border border-border bg-background-elevated px-4 py-3"
              style={{
                contentVisibility: 'auto',
                containIntrinsicSize: 'auto 88px',
              }}
            >
              <SpeakerChip
                meetingId={meetingId}
                speakerId={segment.speaker_id}
                alias={aliasMap[segment.speaker_id] ?? null}
                seriesId={seriesId}
                color={colorFor(segment.speaker_id, speakerIds)}
              />
              <p
                dir={dirOf(segment.text ?? '')}
                className="flex-1 whitespace-pre-wrap break-words text-sm leading-7 text-foreground-secondary"
              >
                {segment.text}
              </p>
              <span
                className="shrink-0 font-mono text-[11px] text-foreground-tertiary tabular-nums"
                dir="ltr"
              >
                {formatTime(segment.start_s)}
              </span>
            </article>
          ))}
        </div>
      )}
    </>
  )
}

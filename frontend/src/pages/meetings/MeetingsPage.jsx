import { forwardRef, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import {
  Calendar,
  Clock,
  Inbox,
  Layers,
  Loader2,
  Mic,
  Search,
  SearchX,
  Users,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import PageHeader from '@/components/layout/PageHeader'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import EmptyState from '@/components/ui/empty-state'
import PageShell from '@/components/layout/PageShell'
import MeetingStatus from './components/MeetingStatus'
import UploadSection from './components/UploadSection'
import { listMeetings } from '@/services/meetingsService'
import { listSeries } from '@/services/meetingSeriesService'
import { cn } from '@/utils/cn'
import { dirOf } from '@/utils/rtl'
import { fmtDistanceToNow } from '@/utils/dateLocale'
import { fmtNumber } from '@/utils/persianLocale'

// Page size for the paginated meeting list. Mirrors the backend default; the
// "load more" button appends one page at a time.
const MEETINGS_PAGE_SIZE = 30

function relative(iso) {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  return fmtDistanceToNow(then, { addSuffix: true })
}

function formatDuration(seconds) {
  if (seconds == null) return null
  const total = Math.max(0, Math.round(seconds))
  const mm = Math.floor(total / 60).toString().padStart(2, '0')
  const ss = (total % 60).toString().padStart(2, '0')
  return `${mm}:${ss}`
}

function MeetingRow({ meeting, series, t }) {
  const meetingId = meeting._id ?? meeting.id
  const label = meeting.title?.trim() || meeting.original_filename
  const duration = formatDuration(meeting.duration_s)
  return (
    <Link
      to={`/meetings/${meetingId}`}
      className="group block rounded-2xl outline-none focus-visible:ring-[3px] focus-visible:ring-accent/40"
    >
      <article
        className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-2xl border border-border bg-card px-4 py-3.5 shadow-card transition-all group-hover:-translate-y-px group-hover:shadow-card-md"
      >
        <div className="min-w-0">
          <div className="mb-1.5 flex items-center gap-2">
            <h3
              dir={dirOf(label)}
              className="truncate text-[14px] font-semibold leading-tight text-foreground"
            >
              {label}
            </h3>
            <MeetingStatus meetingId={meetingId} initialStatus={meeting.status} />
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-foreground-secondary">
            {series && (
              <span
                className="inline-flex items-center gap-1.5"
                dir={dirOf(series.name)}
              >
                <span
                  className="size-[5px] rounded-full bg-amber-500 dark:bg-amber-400"
                  aria-hidden="true"
                />
                <span className="truncate">{series.name}</span>
              </span>
            )}
            {duration && (
              <span
                className="inline-flex items-center gap-1 font-mono tabular-nums"
                dir="ltr"
              >
                <Clock className="size-3" />
                <span>{duration}</span>
              </span>
            )}
            {meeting.num_speakers != null && (
              <span className="inline-flex items-center gap-1">
                <Users className="size-3" />
                <span>{t('card.speakerCount', { count: meeting.num_speakers })}</span>
              </span>
            )}
            <span className="inline-flex items-center gap-1">
              <Calendar className="size-3" />
              <span>{relative(meeting.created_at)}</span>
            </span>
          </div>
        </div>
      </article>
    </Link>
  )
}

const SeriesChip = forwardRef(function SeriesChip(
  { label, count, active, onClick, onKeyDown },
  ref
) {
  return (
    <button
      ref={ref}
      type="button"
      role="tab"
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      onKeyDown={onKeyDown}
      className={cn(
        'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[11px] font-semibold transition-all outline-none focus-visible:ring-[3px] focus-visible:ring-amber-500/40',
        active
          ? 'border-transparent bg-amber-500/10 text-amber-700 dark:bg-amber-400/10 dark:text-amber-300'
          : 'border-border bg-background-secondary text-foreground-secondary hover:bg-background-tertiary'
      )}
      dir={dirOf(label)}
    >
      <span>{label}</span>
      {count != null && (
        <span
          className={cn(
            'rounded-full px-1.5 text-[10px] font-mono tabular-nums',
            active ? 'bg-amber-500/15 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300' : 'bg-background-tertiary text-foreground-tertiary'
          )}
        >
          {fmtNumber(count)}
        </span>
      )}
    </button>
  )
})

export default function MeetingsPage() {
  const { t } = useTranslation('meetings')
  const [searchParams, setSearchParams] = useSearchParams()
  const initialQ = searchParams.get('q') ?? ''
  const [seriesId, setSeriesId] = useState(null)
  const [q, setQ] = useState(initialQ)
  const tabRefs = useRef([])

  // Sync URL ?q= changes
  useEffect(() => {
    const next = searchParams.get('q') ?? ''
    setQ(next)
  }, [searchParams])

  const { data: seriesList } = useQuery({
    queryKey: ['series'],
    queryFn: listSeries,
  })

  const seriesById = useMemo(() => {
    const map = {}
    for (const s of seriesList ?? []) map[s._id ?? s.id] = s
    return map
  }, [seriesList])

  const filterKey = [seriesId ?? '', q.trim()]
  const {
    data,
    isLoading,
    isError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['meetings', ...filterKey],
    queryFn: ({ pageParam = 0 }) =>
      listMeetings({
        series_id: seriesId,
        q: q.trim() || null,
        limit: MEETINGS_PAGE_SIZE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.has_more ? allPages.length * MEETINGS_PAGE_SIZE : undefined,
  })

  const meetings = useMemo(
    () => (data?.pages ?? []).flatMap((page) => page.meetings),
    [data]
  )
  const filtersActive = !!(seriesId || q.trim())
  const count = meetings.length

  function syncQ(value) {
    setQ(value)
    const next = new URLSearchParams(searchParams)
    if (value.trim()) next.set('q', value)
    else next.delete('q')
    setSearchParams(next, { replace: true })
  }

  // Roving-focus arrow-key navigation for the series tablist. RTL-aware:
  // ArrowLeft/ArrowRight resolve to logical prev/next based on document dir.
  function handleTabKeyDown(e, index, tabCount) {
    const isRtl =
      typeof document !== 'undefined' && document.dir === 'rtl'
    let nextIndex = null
    if (e.key === 'ArrowRight') nextIndex = isRtl ? index - 1 : index + 1
    else if (e.key === 'ArrowLeft') nextIndex = isRtl ? index + 1 : index - 1
    else if (e.key === 'Home') nextIndex = 0
    else if (e.key === 'End') nextIndex = tabCount - 1
    if (nextIndex == null) return
    e.preventDefault()
    const clamped = (nextIndex + tabCount) % tabCount
    tabRefs.current[clamped]?.focus()
  }

  return (
    <PageShell width="wide">
        <PageHeader
          title={t('page.title')}
          subtitle={t('page.subtitle')}
          icon={Mic}
          tone="amber"
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <PrivacyBadge mode="cloud" />
              <Button variant="secondary" size="sm" asChild>
                <Link to="/meeting-series">
                  <Layers className="size-4" aria-hidden="true" />
                  <span>{t('page.manageSeries')}</span>
                </Link>
              </Button>
            </div>
          }
        />
        <PrivacyBanner mode="cloud" />

        <UploadSection />

        <section>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <h2 className="text-base font-semibold tracking-tight text-foreground">
              {t('page.recent')}
            </h2>
            {!isLoading && (
              <span className="text-xs text-foreground-tertiary">
                {t('page.count', { count })}
              </span>
            )}
            <div className="ms-auto flex items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute end-3 top-1/2 size-4 -translate-y-1/2 text-foreground-tertiary" />
                <Input
                  dir="auto"
                  value={q}
                  onChange={(e) => syncQ(e.target.value)}
                  placeholder={t('page.searchPlaceholder')}
                  className="w-56 pe-9"
                />
              </div>
            </div>
          </div>

          {(seriesList ?? []).length > 0 && (() => {
            const tabCount = (seriesList ?? []).length + 1
            return (
              <div
                className="mb-4 -mx-1 flex gap-1.5 overflow-x-auto scrollbar-none px-1"
                role="tablist"
                aria-label={t('page.seriesFilterLabel')}
              >
                <SeriesChip
                  ref={(el) => { tabRefs.current[0] = el }}
                  label={t('page.all')}
                  active={seriesId === null}
                  onClick={() => setSeriesId(null)}
                  onKeyDown={(e) => handleTabKeyDown(e, 0, tabCount)}
                />
                {(seriesList ?? []).map((s, i) => {
                  const id = s._id ?? s.id
                  return (
                    <SeriesChip
                      key={id}
                      ref={(el) => { tabRefs.current[i + 1] = el }}
                      label={s.name}
                      count={s.meeting_count}
                      active={seriesId === id}
                      onClick={() => setSeriesId(seriesId === id ? null : id)}
                      onKeyDown={(e) => handleTabKeyDown(e, i + 1, tabCount)}
                    />
                  )
                })}
              </div>
            )
          })()}

          {isLoading ? (
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-[78px] rounded-2xl border border-border bg-background-secondary animate-shimmer"
                />
              ))}
            </div>
          ) : isError ? (
            <div className="rounded-xl border border-error/30 bg-error/5 p-5 text-center text-sm text-error">
              {t('errors.loadList')}
            </div>
          ) : meetings.length === 0 ? (
            filtersActive ? (
              <EmptyState
                icon={SearchX}
                title={t('empty.noResults')}
                description={t('empty.noResultsHint')}
              />
            ) : (
              <EmptyState
                icon={Inbox}
                icon3d="/icons/3d/microphone.png"
                title={t('emptyState.title')}
                description={t('emptyState.description')}
              />
            )
          ) : (
            <>
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {meetings.map((m) => (
                  <MeetingRow
                    key={m._id ?? m.id}
                    meeting={m}
                    series={m.series_id ? seriesById[m.series_id] : undefined}
                    t={t}
                  />
                ))}
              </div>
              {hasNextPage && (
                <div className="mt-4 flex justify-center">
                  <Button
                    variant="outline"
                    onClick={() => fetchNextPage()}
                    disabled={isFetchingNextPage}
                  >
                    {isFetchingNextPage && (
                      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                    )}
                    {t('page.loadMore')}
                  </Button>
                </div>
              )}
            </>
          )}
        </section>
    </PageShell>
  )
}

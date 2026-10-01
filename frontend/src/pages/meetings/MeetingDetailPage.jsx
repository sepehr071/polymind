import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, PanelLeft, StopCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { cn } from '@/utils/cn'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'
import ActionItemsView from './components/ActionItemsView'
import ActionPackView from './components/ActionPackView'
import DecisionsView from './components/DecisionsView'
import DiscussView from './components/DiscussView'
import EmailDraftView from './components/EmailDraftView'
import MeetingSidebar, { MeetingSidebarContent } from './components/MeetingSidebar'
import MinutesView from './components/MinutesView'
import OpenQuestionsView from './components/OpenQuestionsView'
import QaView from './components/QaView'
import SummaryView from './components/SummaryView'
import TranscriptView from './components/TranscriptView'
import { CANCELLED_SENTINEL, IN_FLIGHT } from './components/MeetingStatus'
import {
  cancelMeeting,
  getMeeting,
  getSummary,
  regenerate,
  streamMeetingStatus,
} from '@/services/meetingsService'

function formatDuration(seconds) {
  if (seconds == null) return null
  const total = Math.max(0, Math.round(seconds))
  const mm = Math.floor(total / 60).toString().padStart(2, '0')
  const ss = (total % 60).toString().padStart(2, '0')
  return `${mm}:${ss}`
}

function Panel({ tab, meetingId, meetingReady }) {
  switch (tab) {
    case 'summary':
      return <SummaryView meetingId={meetingId} />
    case 'actions':
      return <ActionItemsView meetingId={meetingId} />
    case 'decisions':
      return <DecisionsView meetingId={meetingId} />
    case 'qa':
      return <QaView meetingId={meetingId} />
    case 'open':
      return <OpenQuestionsView meetingId={meetingId} />
    case 'email':
      return <EmailDraftView meetingId={meetingId} />
    case 'minutes':
      return <MinutesView meetingId={meetingId} />
    case 'transcript':
      return <TranscriptView meetingId={meetingId} />
    case 'discuss':
      return <DiscussView meetingId={meetingId} meetingReady={meetingReady} />
    case 'pack':
      return <ActionPackView meetingId={meetingId} meetingReady={meetingReady} />
    default:
      return null
  }
}

export default function MeetingDetailPage() {
  const { t } = useTranslation('meetings')
  const params = useParams()
  const id = params.id
  const queryClient = useQueryClient()
  const { confirm, confirmDialog } = useConfirmDelete()
  const [tab, setTab] = useState('summary')
  const [sidebarSheetOpen, setSidebarSheetOpen] = useState(false)
  // True once the SSE status stream is live. While it is, the 2s poll below is
  // suppressed (SSE already invalidates on every phase change) — the poll is
  // only a FALLBACK for when SSE is unavailable / drops. Flips back to false on
  // error, on stream cleanup, and on any id/status change so the poll resumes
  // rather than going permanently silent.
  const [sseHealthy, setSseHealthy] = useState(false)

  const meetingQ = useQuery({
    queryKey: ['meeting', id],
    queryFn: () => getMeeting(id),
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s && IN_FLIGHT.has(s) && !sseHealthy ? 2000 : false
    },
  })

  const summaryQ = useQuery({
    queryKey: ['summary', id],
    queryFn: () => getSummary(id),
    enabled: meetingQ.data?.status === 'done',
    retry: false,
  })

  const regenerateMut = useMutation({
    mutationFn: () => regenerate(id),
    onMutate: () => {
      queryClient.setQueryData(['meeting', id], (old) =>
        old ? { ...old, status: 'summarizing' } : old
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting', id] })
      queryClient.invalidateQueries({ queryKey: ['summary', id] })
      toast.success(t('detail.regenerateStarted'))
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : 'error'
      toast.error(`${t('detail.regenerateFailed')}: ${message}`)
    },
  })

  const cancelMut = useMutation({
    mutationFn: () => cancelMeeting(id),
    onMutate: () => {
      queryClient.setQueryData(['meeting', id], (old) =>
        old
          ? { ...old, status: 'failed', error_message: CANCELLED_SENTINEL }
          : old
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting', id] })
      toast.success(t('detail.cancelled'))
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : 'error'
      toast.error(`${t('detail.cancelFailed')}: ${message}`)
      queryClient.invalidateQueries({ queryKey: ['meeting', id] })
    },
  })

  const meeting = meetingQ.data
  const title = meeting?.title?.trim() || meeting?.original_filename || ''
  const duration = formatDuration(meeting?.duration_s ?? null)
  const status = meeting?.status

  // SSE wiring: subscribe while in-flight; invalidate caches on each event.
  // While the stream is live `sseHealthy` suppresses the polling fallback; on
  // drop/error/cleanup it flips back to false so the 2s poll resumes.
  useEffect(() => {
    if (!id) return undefined
    if (!status || !IN_FLIGHT.has(status)) return undefined
    // Re-subscribe (new id/status) starts pessimistic: poll until the stream
    // proves itself live via its first event.
    setSseHealthy(false)
    const ac = new AbortController()
    const stream = streamMeetingStatus(id, {
      onEvent: ({ event }) => {
        // First event = stream is established and delivering — stand the poll
        // down and let SSE drive invalidation.
        setSseHealthy(true)
        if (event === 'phase_change' || event === 'transcript_complete') {
          queryClient.invalidateQueries({ queryKey: ['meeting', id] })
          queryClient.invalidateQueries({ queryKey: ['transcript', id] })
        } else if (event === 'artifact_complete') {
          queryClient.invalidateQueries({ queryKey: ['summary', id] })
        } else if (event === 'meeting_complete' || event === 'error') {
          queryClient.invalidateQueries({ queryKey: ['meeting', id] })
          queryClient.invalidateQueries({ queryKey: ['transcript', id] })
          queryClient.invalidateQueries({ queryKey: ['summary', id] })
        }
      },
      onError: (err) => {
        // Stream dropped — fall back to the react-query polling interval.
        setSseHealthy(false)
        console.warn('[meeting-sse] stream error', err)
      },
      signal: ac.signal,
    })
    return () => {
      // Cleanup also covers id/status change: drop back to polling until the
      // next stream re-establishes.
      setSseHealthy(false)
      ac.abort()
      stream.cancel?.()
    }
  }, [id, status, queryClient])

  // Also: when transitioning into terminal status, invalidate caches once.
  useEffect(() => {
    if (status === 'done' || status === 'failed') {
      queryClient.invalidateQueries({ queryKey: ['meeting', id] })
      queryClient.invalidateQueries({ queryKey: ['transcript', id] })
      queryClient.invalidateQueries({ queryKey: ['summary', id] })
    }
  }, [status, id, queryClient])

  const inFlight = !!(status && IN_FLIGHT.has(status))
  const isCancelled =
    status === 'failed' && meeting?.error_message === CANCELLED_SENTINEL

  // On xl, the summary + transcript pair reads best side-by-side: insight/summary
  // inline-start, transcript inline-end. Below xl it stays a single column on the
  // active tab. Other tabs keep the single 880 reading column.
  const isTwoPaneTab = tab === 'summary' || tab === 'transcript'
  const twoPaneActive = status === 'done' && isTwoPaneTab

  const counts = useMemo(() => {
    const s = summaryQ.data
    return {
      summary: null,
      actions: s?.action_items?.length ?? null,
      decisions: s?.decisions?.length ?? null,
      qa: s?.qa?.length ?? null,
      open: s?.open_questions?.length ?? null,
      email: null,
      minutes: s?.minutes?.length ?? null,
      transcript: null,
    }
  }, [summaryQ.data])

  function handleShare() {
    if (typeof navigator === 'undefined') return
    const url = window.location.href
    void navigator.clipboard
      .writeText(url)
      .then(() => toast.success(t('detail.shareLinkCopied')))
      .catch(() => toast.error(t('detail.shareLinkFailed')))
  }

  async function handleRegenerate() {
    const ok = await confirm({
      title: t('detail.regenerateConfirmTitle'),
      description: t('detail.regenerateConfirmBody'),
      confirmLabel: t('detail.regenerate'),
      destructive: true,
    })
    if (!ok) return
    regenerateMut.mutate()
  }

  async function handleCancel() {
    const ok = await confirm({
      title: t('detail.cancelConfirmTitle'),
      description: t('detail.cancelConfirmBody'),
      confirmLabel: t('processing.cancelStop'),
      destructive: true,
    })
    if (!ok) return
    cancelMut.mutate()
  }

  const sidebarProps = {
    meetingId: id,
    title,
    duration,
    speakerCount: meeting?.speakers?.length ?? null,
    createdAt: meeting?.created_at ?? null,
    active: tab,
    counts,
    initialStatus: meeting?.status,
    onShare: handleShare,
    onRegenerate: handleRegenerate,
    regenDisabled: regenerateMut.isPending || !meeting || status !== 'done',
    regenPending: regenerateMut.isPending,
    discussDisabled: status !== 'done',
  }

  // Mobile (< md) sidebar: same content surfaced in a left Sheet. Selecting a
  // tab also closes the sheet so the chosen panel is visible immediately.
  const mobileSidebarTrigger = (
    <Sheet open={sidebarSheetOpen} onOpenChange={setSidebarSheetOpen}>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label={t('detail.sections')}
        >
          <PanelLeft className="size-5" />
        </Button>
      </SheetTrigger>
      <SheetContent side="left" className="w-72 p-0 flex flex-col">
        <SheetHeader className="px-4 py-3 border-b border-border text-start">
          <SheetTitle>{title || t('detail.sections')}</SheetTitle>
        </SheetHeader>
        <div className="flex flex-1 flex-col overflow-y-auto">
          <MeetingSidebarContent
            {...sidebarProps}
            onSelect={(next) => {
              setTab(next)
              setSidebarSheetOpen(false)
            }}
          />
        </div>
      </SheetContent>
    </Sheet>
  )

  return (
    <div className="flex h-full min-h-0">
      <MeetingSidebar
        className="hidden md:flex"
        {...sidebarProps}
        onSelect={setTab}
      />
      <main className={tab === 'discuss' ? 'flex flex-col flex-1 min-h-0 bg-background' : 'flex-1 overflow-y-auto bg-background scroll-thin'}>
        {tab === 'discuss' && status !== 'failed' ? (
          <>
            <header className="flex shrink-0 items-start gap-2 border-b border-border px-4 py-3.5 md:px-6">
              {mobileSidebarTrigger}
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
                  {t('panels.discuss.kicker')}
                </p>
                <h1 className="mt-0.5 text-base font-bold leading-tight tracking-tight text-foreground">
                  {t('panels.discuss.title')}
                </h1>
                <p className="mt-0.5 text-xs text-foreground-secondary">
                  {t('panels.discuss.subtitle')}
                </p>
              </div>
            </header>
            <div className="min-h-0 flex-1">
              <Panel tab={tab} meetingId={id} meetingReady={status === 'done'} />
            </div>
          </>
        ) : (
          <div
            className={cn(
              // Single-column tabs stay centered (880 reading lane). Two-pane
              // (transcript + summary) widens, still centered — no dead end-gutter.
              'mx-auto max-w-[880px] px-4 py-9 pb-20 md:px-10',
              twoPaneActive && 'xl:max-w-[1560px]'
            )}
          >
            <div className="mb-4 md:hidden">{mobileSidebarTrigger}</div>
            {inFlight && (
              <div className="mb-6 flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-700 dark:border-amber-400/30 dark:bg-amber-400/5 dark:text-amber-300">
                <span
                  className="size-2 shrink-0 rounded-full bg-amber-500 animate-pulse-dot dark:bg-amber-400"
                  aria-hidden="true"
                />
                <span className="flex-1" aria-live="polite" aria-atomic="true">
                  {t(`processing.${status}`, { defaultValue: t('processing.default') })}
                </span>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleCancel}
                  disabled={cancelMut.isPending}
                  className="gap-1.5"
                >
                  <StopCircle
                    className={cancelMut.isPending ? 'animate-pulse' : undefined}
                  />
                  {t('processing.cancelStop')}
                </Button>
              </div>
            )}

            {status === 'failed' ? (
              isCancelled ? (
                <div className="rounded-2xl border border-border bg-card p-6 shadow-card">
                  <p className="text-base font-semibold text-foreground">
                    {t('processing.cancelledTitle')}
                  </p>
                  <p className="mt-1 text-sm text-foreground-secondary">
                    {t('processing.cancelledHint')}
                  </p>
                </div>
              ) : (
                <div className="flex items-start gap-3 rounded-2xl border border-error/30 bg-error/5 p-5">
                  <AlertTriangle className="mt-0.5 size-5 shrink-0 text-error" />
                  <div>
                    <p className="text-sm font-semibold text-error">
                      {t('processing.errorTitle')}
                    </p>
                    <p className="mt-1 text-sm text-foreground-secondary">
                      {meeting?.error_message || t('processing.errorUnknown')}
                    </p>
                  </div>
                </div>
              )
            ) : twoPaneActive ? (
              <>
                {/* < xl: single active panel (880 reading column, unchanged). */}
                <div className="xl:hidden">
                  <Panel
                    tab={tab}
                    meetingId={id}
                    meetingReady={status === 'done'}
                  />
                </div>
                {/* xl: insight/summary inline-start + transcript inline-end,
                    each pane capped at its 760 prose lane. */}
                <div className="hidden xl:grid xl:grid-cols-2 xl:gap-8">
                  <div className="min-w-0 max-w-[760px]">
                    <SummaryView meetingId={id} />
                  </div>
                  <div className="min-w-0 max-w-[760px]">
                    <TranscriptView meetingId={id} />
                  </div>
                </div>
              </>
            ) : (
              <Panel tab={tab} meetingId={id} meetingReady={status === 'done'} />
            )}
          </div>
        )}
      </main>
      {confirmDialog}
    </div>
  )
}

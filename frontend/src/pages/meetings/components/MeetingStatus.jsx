import { useQuery } from '@tanstack/react-query'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/utils/cn'
import { useTranslation } from 'react-i18next'
import { getMeeting } from '@/services/meetingsService'

const CANCELLED_SENTINEL = 'cancelled by user'
// Genuinely in-flight states that warrant polling. `uploaded` is the transient
// pre-transcription state (background pipeline hasn't flipped to `transcribing`
// yet); `queued`/`processing` only appear as i18n labels but are polled
// defensively in case the backend ever emits them. Terminal states (`done`,
// `failed`, `cancelled`) never poll and render straight from `initialStatus`.
const IN_FLIGHT = new Set([
  'uploaded',
  'queued',
  'processing',
  'transcribing',
  'summarizing',
])

function styleFor(status, isCancelled) {
  if (status === 'done') {
    return {
      tone: 'success',
      animate: false,
    }
  }
  if (status === 'failed') {
    if (isCancelled) return { tone: 'muted', animate: false }
    return { tone: 'error', animate: false }
  }
  if (status === 'uploaded') return { tone: 'muted', animate: true }
  return { tone: 'accent', animate: true } // transcribing / summarizing
}

const TONE_CLASSES = {
  success: 'bg-success/10 text-success',
  muted: 'bg-background-tertiary text-foreground-secondary',
  error: 'bg-error/10 text-error',
  accent: 'bg-accent/10 text-accent',
}

const DOT_CLASSES = {
  success: 'bg-success',
  muted: 'bg-foreground-tertiary',
  error: 'bg-error',
  accent: 'bg-accent',
}

/**
 * Status pill backed by react-query polling. Re-uses the cached meeting doc
 * so a single fetch fills both the row and the detail header.
 */
export default function MeetingStatus({
  meetingId,
  initialStatus,
  initialError,
  className,
}) {
  const { t } = useTranslation('meetings')
  // Seed the cache from the list payload so terminal rows render without a
  // request. `done`/`cancelled` rows never fetch; in-flight rows fetch + poll
  // until terminal. A `failed` row only fetches when the caller didn't already
  // hand us its `error_message` (the list payload carries it) — so a screen
  // full of done/failed rows triggers ZERO per-row getMeeting fan-out.
  const needsFetch =
    !initialStatus ||
    IN_FLIGHT.has(initialStatus) ||
    (initialStatus === 'failed' && initialError == null)
  const { data, isLoading } = useQuery({
    queryKey: ['meeting', meetingId],
    queryFn: () => getMeeting(meetingId),
    initialData: initialStatus
      ? { status: initialStatus, error_message: initialError ?? undefined }
      : undefined,
    enabled: needsFetch,
    // Terminal rows are immutable; only poll the genuinely in-flight ones.
    staleTime: needsFetch && IN_FLIGHT.has(initialStatus) ? 5000 : Infinity,
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s && IN_FLIGHT.has(s) ? 2000 : false
    },
  })

  const status = data?.status ?? initialStatus

  if (!status) {
    if (isLoading) {
      return (
        <span
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full bg-background-tertiary px-2.5 py-0.5 text-[11px] font-medium text-foreground-tertiary',
            className
          )}
        >
          …
        </span>
      )
    }
    return null
  }

  const isCancelled =
    status === 'failed' && data?.error_message === CANCELLED_SENTINEL

  const labelKey = isCancelled ? 'cancelled' : status
  const s = styleFor(status, isCancelled)

  const pill = (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-[3px] text-[11px] font-medium',
        TONE_CLASSES[s.tone],
        className
      )}
    >
      <span
        className={cn(
          'size-1.5 rounded-full',
          DOT_CLASSES[s.tone],
          s.animate && 'animate-pulse-dot'
        )}
        aria-hidden="true"
      />
      <span>{t(`status.${labelKey}`)}</span>
    </span>
  )

  if (status === 'failed' && data?.error_message && !isCancelled) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0}>{pill}</span>
        </TooltipTrigger>
        <TooltipContent>{data.error_message}</TooltipContent>
      </Tooltip>
    )
  }

  return pill
}

export { CANCELLED_SENTINEL, IN_FLIGHT }

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Monitor, Square, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/utils/cn'
import { uploadMeeting } from '@/services/meetingsService'
import { fmtNumber } from '@/utils/persianLocale'

const SOFT_LIMIT_S = 6300
const HARD_LIMIT_S = 7200
const EQ_BARS = 14

function formatTimer(total) {
  const s = Math.max(0, Math.floor(total))
  const mm = Math.floor(s / 60).toString().padStart(2, '0')
  const ss = (s % 60).toString().padStart(2, '0')
  return `${mm}:${ss}`
}

// Memoized so the 10Hz `level` updates that drive the bars don't ride along
// with unrelated parent re-renders (timer tick, etc.) — only height/active
// changes reconcile here.
const EqMeter = memo(function EqMeter({ level, active }) {
  const bars = useMemo(() => Array.from({ length: EQ_BARS }), [])
  return (
    <div className="flex h-9 flex-1 items-end gap-[3px]" aria-hidden="true">
      {bars.map((_, i) => {
        const center = (EQ_BARS - 1) / 2
        const distance = Math.abs(i - center) / center
        const intensity = Math.max(0.06, level * (1 - distance * 0.7))
        const heightPct = Math.min(100, 16 + intensity * 110)
        return (
          <span
            key={i}
            style={{ height: `${heightPct}%` }}
            className={cn(
              'w-[3px] rounded-full transition-[height,background-color] duration-100',
              active ? 'bg-accent/80' : 'bg-foreground-tertiary/30'
            )}
          />
        )
      })}
    </div>
  )
})

/**
 * Tab recorder. Captures via getDisplayMedia (video tracks dropped),
 * optionally mixed with mic. Live captions removed.
 */
export default function TabRecorder({
  title,
  numSpeakers,
  meetingBrief,
  seriesId,
  onUploaded,
  inline = false,
}) {
  const { t } = useTranslation('meetings')
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [level, setLevel] = useState(0)
  const [error, setError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadPercent, setUploadPercent] = useState(0)
  const [withMic, setWithMic] = useState(true)

  const tabStreamRef = useRef(null)
  const micStreamRef = useRef(null)
  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])
  const audioCtxRef = useRef(null)
  const tabSourceRef = useRef(null)
  const micSourceRef = useRef(null)
  const mixDestRef = useRef(null)
  const analyserRef = useRef(null)
  const timerIntervalRef = useRef(null)
  const levelIntervalRef = useRef(null)
  const softWarnedRef = useRef(false)

  const cleanupAll = useCallback(() => {
    if (timerIntervalRef.current) {
      clearInterval(timerIntervalRef.current)
      timerIntervalRef.current = null
    }
    if (levelIntervalRef.current) {
      clearInterval(levelIntervalRef.current)
      levelIntervalRef.current = null
    }
    for (const ref of [tabSourceRef, micSourceRef]) {
      if (ref.current) {
        try { ref.current.disconnect() } catch { /* ignore */ }
        ref.current = null
      }
    }
    if (mixDestRef.current) {
      try { mixDestRef.current.disconnect() } catch { /* ignore */ }
      mixDestRef.current = null
    }
    if (analyserRef.current) {
      try { analyserRef.current.disconnect() } catch { /* ignore */ }
      analyserRef.current = null
    }
    if (audioCtxRef.current) {
      try { void audioCtxRef.current.close() } catch { /* ignore */ }
      audioCtxRef.current = null
    }
    if (mediaRecorderRef.current) {
      try {
        if (mediaRecorderRef.current.state !== 'inactive') {
          mediaRecorderRef.current.stop()
        }
      } catch { /* ignore */ }
      mediaRecorderRef.current = null
    }
    for (const ref of [tabStreamRef, micStreamRef]) {
      if (ref.current) {
        ref.current.getTracks().forEach((tr) => tr.stop())
        ref.current = null
      }
    }
  }, [])

  useEffect(() => () => cleanupAll(), [cleanupAll])

  const stopRecording = useCallback(async () => {
    const recorder = mediaRecorderRef.current
    if (!recorder) {
      cleanupAll()
      return null
    }
    if (timerIntervalRef.current) {
      clearInterval(timerIntervalRef.current)
      timerIntervalRef.current = null
    }
    if (levelIntervalRef.current) {
      clearInterval(levelIntervalRef.current)
      levelIntervalRef.current = null
    }
    const stopped = new Promise((resolve) => {
      if (recorder.state === 'inactive') {
        resolve()
        return
      }
      recorder.addEventListener('stop', () => resolve(), { once: true })
      try { recorder.stop() } catch { resolve() }
    })
    await stopped
    const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
    chunksRef.current = []
    cleanupAll()
    return blob
  }, [cleanupAll])

  const handleStop = useCallback(async () => {
    setRecording(false)
    setUploading(true)
    setUploadPercent(0)
    try {
      const blob = await stopRecording()
      if (!blob || blob.size === 0) {
        setUploading(false)
        return
      }
      const meeting = await uploadMeeting(blob, {
        title,
        num_speakers: numSpeakers ?? null,
        meeting_brief: meetingBrief,
        series_id: seriesId ?? null,
        filename: 'tab-recording.webm',
        onUploadProgress: setUploadPercent,
      })
      toast.success(t('upload.tabRecordSuccess'))
      onUploaded?.(meeting._id ?? meeting.id)
      setSeconds(0)
      setLevel(0)
      softWarnedRef.current = false
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      toast.error(`${t('upload.uploadFailed')}: ${msg}`)
    } finally {
      setUploading(false)
      setUploadPercent(0)
    }
  }, [meetingBrief, numSpeakers, onUploaded, seriesId, stopRecording, t, title])

  const handleStart = useCallback(async () => {
    setError(null)
    setSeconds(0)
    setLevel(0)
    softWarnedRef.current = false

    let displayStream
    try {
      displayStream = await navigator.mediaDevices.getDisplayMedia({
        audio: true,
        video: true,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(t('recorder.tabShareDeniedDetail', { message: msg }))
      toast.error(t('recorder.tabShareDenied'))
      return
    }

    displayStream.getVideoTracks().forEach((tr) => tr.stop())

    if (displayStream.getAudioTracks().length === 0) {
      displayStream.getTracks().forEach((tr) => tr.stop())
      setError(t('recorder.tabNoAudio'))
      toast.error(t('recorder.tabNoAudioToast'))
      return
    }
    tabStreamRef.current = displayStream

    displayStream.getAudioTracks()[0].addEventListener('ended', () => {
      void handleStop()
    })

    let micStream = null
    if (withMic) {
      try {
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
        })
        micStreamRef.current = micStream
      } catch (err) {
        console.warn('[tab-recorder] mic denied, continuing tab-only', err)
        toast(t('recorder.micUnavailable'))
      }
    }

    let audioCtx
    try {
      audioCtx = new AudioContext({ sampleRate: 48000 })
    } catch {
      audioCtx = new AudioContext()
    }
    audioCtxRef.current = audioCtx

    const tabSource = audioCtx.createMediaStreamSource(displayStream)
    tabSourceRef.current = tabSource

    const mixDest = audioCtx.createMediaStreamDestination()
    mixDestRef.current = mixDest
    tabSource.connect(mixDest)

    if (micStream) {
      const micSource = audioCtx.createMediaStreamSource(micStream)
      micSourceRef.current = micSource
      micSource.connect(mixDest)
    }

    const recorderStream = mixDest.stream
    let recorder
    try {
      recorder = new MediaRecorder(recorderStream, {
        mimeType: 'audio/webm;codecs=opus',
        audioBitsPerSecond: 64000,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(t('recorder.recorderUnavailableDetail', { message: msg }))
      toast.error(t('recorder.recorderUnavailable'))
      cleanupAll()
      return
    }
    chunksRef.current = []
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunksRef.current.push(e.data)
    }
    mediaRecorderRef.current = recorder
    recorder.start(1000)

    const analyser = audioCtx.createAnalyser()
    analyser.fftSize = 256
    analyserRef.current = analyser

    const mixSource = audioCtx.createMediaStreamSource(recorderStream)
    mixSource.connect(analyser)

    setRecording(true)

    timerIntervalRef.current = setInterval(() => {
      setSeconds((prev) => {
        const next = prev + 1
        if (next >= HARD_LIMIT_S) {
          void handleStop()
        } else if (!softWarnedRef.current && next >= SOFT_LIMIT_S) {
          softWarnedRef.current = true
          toast(t('recorder.approachingLimit'))
        }
        return next
      })
    }, 1000)

    const data = new Uint8Array(analyser.fftSize)
    levelIntervalRef.current = setInterval(() => {
      if (!analyserRef.current) return
      analyserRef.current.getByteTimeDomainData(data)
      let sumSq = 0
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128
        sumSq += v * v
      }
      const rms = Math.sqrt(sumSq / data.length)
      setLevel(Math.min(1, rms * 1.6))
    }, 100)
  }, [cleanupAll, handleStop, t, withMic])

  const onClick = useCallback(() => {
    if (uploading) return
    if (recording) {
      void handleStop()
    } else {
      void handleStart()
    }
  }, [handleStart, handleStop, recording, uploading])

  const buttonLabel = uploading
    ? t('recorder.uploading')
    : recording
      ? t('recorder.stop')
      : t('recorder.tabRecordStart')

  const body = (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={onClick}
          disabled={uploading}
          aria-label={buttonLabel}
          className={cn(
            'relative grid size-14 shrink-0 place-items-center rounded-full text-white shadow-sm transition-all outline-none',
            'focus-visible:ring-[3px] focus-visible:ring-accent/50',
            'active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60',
            recording
              ? 'bg-error hover:bg-error/90'
              : 'bg-accent hover:bg-accent-hover'
          )}
        >
          {recording && (
            <span
              className="absolute inset-0 -z-10 rounded-full ring-4 ring-error/40 animate-record-ring"
              aria-hidden="true"
            />
          )}
          {uploading ? (
            <Loader2 className="size-5 animate-spin" />
          ) : recording ? (
            <Square className="size-5 fill-current" />
          ) : (
            <Monitor className="size-5" />
          )}
        </button>
        <div className="flex-1 space-y-1.5">
          <div className="flex items-center justify-between text-sm">
            <span
              className="font-mono text-base font-semibold tabular-nums"
              dir="ltr"
            >
              {formatTimer(seconds)}
            </span>
            <span
              className={cn(
                'inline-flex items-center gap-1.5 text-xs font-medium',
                recording
                  ? 'text-error'
                  : uploading
                    ? 'text-accent'
                    : 'text-foreground-secondary'
              )}
            >
              {recording && (
                <span
                  className="size-1.5 rounded-full bg-error animate-pulse-dot"
                  aria-hidden="true"
                />
              )}
              {recording
                ? t('recorder.recording')
                : uploading
                  ? t('recorder.uploadingProgress', {
                      percent: fmtNumber(uploadPercent),
                    })
                  : t('recorder.ready')}
            </span>
          </div>
          <EqMeter level={level} active={recording} />
        </div>
      </div>

      {uploading ? (
        <div aria-live="polite">
          <Progress value={uploadPercent} />
        </div>
      ) : null}

      <label className="flex items-center gap-2 text-sm text-foreground-secondary">
        <input
          type="checkbox"
          checked={withMic}
          onChange={(e) => setWithMic(e.target.checked)}
          disabled={recording || uploading}
          className="size-4 rounded border-border accent-accent"
        />
        <span>{t('recorder.withMicLabel')}</span>
      </label>

      <p className="rounded-md border border-border bg-background-tertiary/30 px-3 py-2 text-xs leading-6 text-foreground-secondary">
        {t('recorder.tabHelp')}
      </p>

      {error ? (
        <p className="text-sm text-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )

  if (inline) return body

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('recorder.tabRecordTitle')}</CardTitle>
      </CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  )
}

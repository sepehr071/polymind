import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronUp,
  FileAudio,
  Mic,
  MonitorPlay,
  Plus,
  Sparkles,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Progress } from '@/components/ui/progress'
import Dropzone from './Dropzone'
import Recorder from './Recorder'
import TabRecorder from './TabRecorder'
import { uploadMeeting, suggestSeries } from '@/services/meetingsService'
import { listSeries, createSeries } from '@/services/meetingSeriesService'
import { cn } from '@/utils/cn'
import { dirOf } from '@/utils/rtl'
import { fmtNumber } from '@/utils/persianLocale'

const NONE_SENTINEL = '__none'

export default function UploadSection() {
  const { t } = useTranslation('meetings')
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [mode, setMode] = useState('file')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [numSpeakersStr, setNumSpeakersStr] = useState('')
  const [meetingBrief, setMeetingBrief] = useState('')
  const [seriesId, setSeriesId] = useState(null)
  const [suggestion, setSuggestion] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadPercent, setUploadPercent] = useState(0)
  const [newSeriesName, setNewSeriesName] = useState('')
  const [newSeriesOpen, setNewSeriesOpen] = useState(false)

  const MODES = [
    { id: 'file', label: t('upload.modeFile'), Icon: FileAudio },
    { id: 'mic', label: t('upload.modeMic'), Icon: Mic },
    { id: 'tab', label: t('upload.modeTab'), Icon: MonitorPlay },
  ]

  const { data: seriesList } = useQuery({
    queryKey: ['series'],
    queryFn: listSeries,
  })

  const seriesById = useMemo(() => {
    const map = {}
    for (const s of seriesList ?? []) map[s._id ?? s.id] = s
    return map
  }, [seriesList])

  useEffect(() => {
    const trimmed = title.trim()
    if (!trimmed || seriesId) {
      setSuggestion(null)
      return
    }
    const handle = setTimeout(async () => {
      try {
        const s = await suggestSeries(trimmed)
        setSuggestion(s)
      } catch {
        setSuggestion(null)
      }
    }, 350)
    return () => clearTimeout(handle)
  }, [title, seriesId])

  const numSpeakers = numSpeakersStr.trim()
    ? Math.max(1, Math.min(32, Number.parseInt(numSpeakersStr, 10) || 0)) || null
    : null

  function clearFields() {
    setTitle('')
    setNumSpeakersStr('')
    setMeetingBrief('')
    setSeriesId(null)
    setSuggestion(null)
  }

  async function handleCreateSeries() {
    const name = newSeriesName.trim()
    if (!name) return
    try {
      const s = await createSeries({ name })
      setNewSeriesName('')
      setNewSeriesOpen(false)
      setSeriesId(s._id ?? s.id)
      queryClient.invalidateQueries({ queryKey: ['series'] })
      toast.success(t('upload.seriesCreated'))
    } catch (e) {
      toast.error(String(e))
    }
  }

  async function handleFile(file) {
    if (uploading) return
    setUploading(true)
    setUploadPercent(0)
    try {
      const meeting = await uploadMeeting(file, {
        title: title.trim() || undefined,
        num_speakers: numSpeakers,
        meeting_brief: meetingBrief.trim() || undefined,
        series_id: seriesId ?? undefined,
        onUploadProgress: setUploadPercent,
      })
      toast.success(t('upload.uploadSuccess'))
      clearFields()
      queryClient.invalidateQueries({ queryKey: ['meetings'] })
      navigate(`/meetings/${meeting._id ?? meeting.id}`)
    } catch (err) {
      const message = err instanceof Error ? err.message : t('upload.uploadFailed')
      toast.error(`${t('upload.uploadFailed')}: ${message}`)
    } finally {
      setUploading(false)
      setUploadPercent(0)
    }
  }

  const activeSeries = seriesId ? seriesById[seriesId] : null
  const suggestionId = suggestion?.series_id ?? suggestion?._id ?? suggestion?.id

  return (
    <section className="rounded-2xl border border-border bg-card p-5 shadow-card sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">
            {t('upload.sectionTitle')}
          </h2>
          <p className="mt-0.5 text-xs text-foreground-secondary">
            {t('upload.sectionSubtitle')}
          </p>
        </div>
        <div
          className="flex gap-1 rounded-[11px] border border-border bg-background-secondary p-1"
          role="tablist"
        >
          {MODES.map((m) => {
            const active = mode === m.id
            const Icon = m.Icon
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => setMode(m.id)}
                role="tab"
                aria-selected={active}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs transition-all',
                  active
                    ? 'bg-background font-semibold text-foreground shadow-card'
                    : 'text-foreground-secondary hover:text-foreground'
                )}
              >
                <Icon className="size-3.5" />
                {m.label}
              </button>
            )
          })}
        </div>
      </div>

      <div className="mb-4">
        {mode === 'file' && (
          <>
            <Dropzone onFilePicked={handleFile} disabled={uploading} />
            {uploading && (
              <div className="mt-3 space-y-1.5" aria-live="polite">
                <p className="text-xs font-medium text-foreground-secondary">
                  {t('upload.uploadingProgress', {
                    percent: fmtNumber(uploadPercent),
                  })}
                </p>
                <Progress value={uploadPercent} />
              </div>
            )}
          </>
        )}
        {mode === 'mic' && (
          <div className="rounded-xl border border-border bg-background p-4">
            <Recorder
              inline
              title={title.trim() || undefined}
              numSpeakers={numSpeakers}
              meetingBrief={meetingBrief.trim() || undefined}
              seriesId={seriesId}
              onUploaded={(id) => {
                clearFields()
                queryClient.invalidateQueries({ queryKey: ['meetings'] })
                navigate(`/meetings/${id}`)
              }}
            />
          </div>
        )}
        {mode === 'tab' && (
          <div className="rounded-xl border border-border bg-background p-4">
            <TabRecorder
              inline
              title={title.trim() || undefined}
              numSpeakers={numSpeakers}
              meetingBrief={meetingBrief.trim() || undefined}
              seriesId={seriesId}
              onUploaded={(id) => {
                clearFields()
                queryClient.invalidateQueries({ queryKey: ['meetings'] })
                navigate(`/meetings/${id}`)
              }}
            />
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 items-end gap-3 md:grid-cols-[1.4fr_1fr_140px_auto]">
        <Field label={t('upload.titleLabel')}>
          <Input
            id="meeting-title"
            dir="auto"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t('upload.titlePlaceholder')}
            disabled={uploading}
          />
        </Field>
        <Field label={t('upload.seriesLabel')}>
          <div className="flex gap-1.5">
            <Select
              value={seriesId ?? NONE_SENTINEL}
              onValueChange={(v) => setSeriesId(v === NONE_SENTINEL ? null : v)}
              disabled={uploading}
            >
              <SelectTrigger className="h-[42px] flex-1">
                <SelectValue placeholder={t('upload.seriesNone')}>
                  {activeSeries ? activeSeries.name : t('upload.seriesNone')}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE_SENTINEL}>
                  {t('upload.seriesNone')}
                </SelectItem>
                {(seriesList ?? []).map((s) => (
                  <SelectItem key={s._id ?? s.id} value={s._id ?? s.id}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Popover open={newSeriesOpen} onOpenChange={setNewSeriesOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  disabled={uploading}
                  className="h-[42px] w-[42px] shrink-0"
                  aria-label={t('upload.newSeries')}
                >
                  <Plus className="size-4" />
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-72 space-y-2">
                <Input
                  dir="auto"
                  value={newSeriesName}
                  onChange={(e) => setNewSeriesName(e.target.value)}
                  placeholder={t('upload.newSeriesName')}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newSeriesName.trim()) {
                      void handleCreateSeries()
                    }
                  }}
                />
                <Button
                  size="sm"
                  onClick={handleCreateSeries}
                  disabled={!newSeriesName.trim()}
                  className="w-full"
                >
                  {t('upload.create')}
                </Button>
              </PopoverContent>
            </Popover>
          </div>
        </Field>
        <Field label={t('upload.numSpeakersLabel')}>
          <Input
            id="meeting-num-speakers"
            type="number"
            min={1}
            max={32}
            inputMode="numeric"
            value={numSpeakersStr}
            onChange={(e) => setNumSpeakersStr(e.target.value)}
            placeholder={t('upload.numSpeakersAuto')}
            disabled={uploading}
          />
        </Field>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setAdvancedOpen((v) => !v)}
          className="h-[42px] px-3"
        >
          {advancedOpen ? (
            <ChevronUp className="size-3.5" />
          ) : (
            <ChevronDown className="size-3.5" />
          )}
          <span>{t('upload.advanced')}</span>
        </Button>
      </div>

      {suggestion && !seriesId && suggestionId && (
        <button
          type="button"
          onClick={() => setSeriesId(suggestionId)}
          className="mt-3 inline-flex items-center gap-1.5 text-xs text-amber-700 underline-offset-2 hover:underline dark:text-amber-300"
          dir={dirOf(suggestion.name)}
        >
          <Sparkles className="size-3" />
          <span>
            {t('upload.suggestSeries', { name: suggestion.name })}
          </span>
        </button>
      )}

      {advancedOpen && (
        <div className="mt-5 space-y-4 border-t border-border pt-5">
          <div className="space-y-1.5">
            <label
              htmlFor="meeting-brief"
              className="block text-[13px] font-semibold text-foreground"
            >
              {t('upload.briefLabel')}{' '}
              <span className="font-normal text-foreground-tertiary">{t('upload.briefOptional')}</span>
            </label>
            <Textarea
              id="meeting-brief"
              dir="auto"
              value={meetingBrief}
              onChange={(e) => setMeetingBrief(e.target.value)}
              placeholder={t('upload.briefPlaceholder')}
              disabled={uploading}
              rows={3}
            />
            <p className="text-xs leading-5 text-foreground-tertiary">
              {t('upload.briefHint')}
            </p>
          </div>

          {activeSeries && (
            <p className="text-xs text-foreground-secondary">
              {t('upload.toneLabel')}:{' '}
              <span className="font-medium text-foreground">
                {activeSeries.email_tone === 'formal'
                  ? t('upload.toneFormal')
                  : t('upload.toneCasual')}
              </span>
            </p>
          )}
        </div>
      )}
    </section>
  )
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-semibold text-foreground">
        {label}
      </span>
      {children}
    </label>
  )
}

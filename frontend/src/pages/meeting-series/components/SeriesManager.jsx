import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Layers, Plus, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
  AlertDialogAction,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import EmptyState from '@/components/ui/empty-state'
import {
  acceptKeyterm,
  addKeyterm,
  createSeries,
  deleteSeries,
  listKeyterms,
  listSeries,
  listSeriesSpeakerNames,
  rejectKeyterm,
  updateSeries,
} from '@/services/meetingSeriesService'
import { cn } from '@/utils/cn'
import { dirOf } from '@/utils/rtl'

const errMsg = (e, fallback) => e?.response?.data?.error || fallback

export default function SeriesManager() {
  const { t } = useTranslation('meetings_series')
  const qc = useQueryClient()
  const [selectedId, setSelectedId] = useState(null)
  const [newName, setNewName] = useState('')

  const {
    data: seriesList,
    isLoading: seriesLoading,
    isError: seriesError,
    refetch: refetchSeries,
  } = useQuery({
    queryKey: ['series'],
    queryFn: listSeries,
  })

  const create = useMutation({
    mutationFn: () => createSeries({ name: newName.trim() }),
    onSuccess: (s) => {
      setNewName('')
      qc.invalidateQueries({ queryKey: ['series'] })
      setSelectedId(s._id ?? s.id)
      toast.success(t('form.seriesCreated'))
    },
    onError: (e) => toast.error(errMsg(e, t('errors.create'))),
  })

  const items = seriesList ?? []
  const selected = items.find((s) => (s._id ?? s.id) === selectedId)

  return (
    <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
      <aside className="space-y-3">
        <div className="space-y-2 rounded-[14px] border border-border bg-background-secondary p-3 shadow-card">
          <p className="text-[13px] font-semibold text-foreground">
            {t('form.newSeriesLabel')}
          </p>
          <div className="flex gap-2">
            <Input
              dir="auto"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder={t('form.namePlaceholder')}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newName.trim()) create.mutate()
              }}
            />
            <Button
              size="icon"
              onClick={() => create.mutate()}
              disabled={!newName.trim() || create.isPending}
              aria-label={t('form.create')}
              className="h-[42px] w-[42px] shrink-0"
            >
              <Plus className="size-4" />
            </Button>
          </div>
        </div>
        {seriesLoading ? (
          <ul className="space-y-1" aria-busy="true" aria-live="polite">
            {Array.from({ length: 4 }).map((_, i) => (
              <li key={i} className="h-10 rounded-md animate-shimmer" />
            ))}
          </ul>
        ) : seriesError ? (
          <EmptyState
            icon={AlertTriangle}
            tone="destructive"
            title={t('errors.loadSeries')}
          >
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetchSeries()}
              className="mt-1 h-8 border-border"
            >
              {t('errors.retry')}
            </Button>
          </EmptyState>
        ) : items.length === 0 ? (
          <EmptyState icon={Layers} title={t('empty.title')} hint={t('empty.hint')} />
        ) : (
          <ul className="space-y-1">
            {items.map((s) => {
              const id = s._id ?? s.id
              const active = selectedId === id
              return (
                <li key={id}>
                  <button
                    onClick={() => setSelectedId(id)}
                    aria-current={active ? 'true' : undefined}
                    className={cn(
                      'w-full rounded-[9px] px-3 py-2 text-start text-sm transition-colors',
                      active
                        ? 'bg-amber-500/10 font-semibold text-amber-700 ring-1 ring-inset ring-amber-500/25 dark:bg-amber-400/10 dark:text-amber-300 dark:ring-amber-400/25'
                        : 'text-foreground-secondary hover:bg-background-tertiary'
                    )}
                    dir={dirOf(s.name)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate">{s.name}</span>
                      <span
                        className={cn(
                          'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-mono tabular-nums',
                          active
                            ? 'bg-amber-500/15 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300'
                            : 'bg-background-tertiary text-foreground-tertiary'
                        )}
                      >
                        {s.meeting_count ?? 0}
                      </span>
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </aside>

      {selected ? (
        <SeriesDetail
          series={selected}
          onDeleted={() => setSelectedId(null)}
        />
      ) : (
        <EmptyState
          icon={Layers}
          title={t('empty.selectPrompt')}
          hint={t('empty.selectPromptHint')}
        />
      )}
    </div>
  )
}

function SeriesDetail({ series, onDeleted }) {
  const { t } = useTranslation('meetings_series')
  const qc = useQueryClient()
  const seriesId = series._id ?? series.id

  const update = useMutation({
    mutationFn: (patch) => updateSeries(seriesId, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['series'] })
      toast.success(t('form.saved'))
    },
    onError: (e) => toast.error(errMsg(e, t('errors.save'))),
  })

  const remove = useMutation({
    mutationFn: () => deleteSeries(seriesId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['series'] })
      onDeleted()
      toast.success(t('form.deleted'))
    },
    onError: (e) => toast.error(errMsg(e, t('errors.delete'))),
  })

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-border bg-card p-5 shadow-card">
        <div className="mb-4">
          <h2
            dir={dirOf(series.name)}
            className="text-[18px] font-bold tracking-tight text-foreground"
          >
            {series.name}
          </h2>
          <p className="mt-0.5 text-xs text-foreground-secondary">
            {t('form.meetingCount', { count: series.meeting_count ?? 0 })}
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-[1fr_auto_auto]">
          <SeriesNameField
            series={series}
            onSave={(name) => update.mutate({ name })}
          />
          <ToneSelector
            value={series.email_tone}
            onChange={(tone) => update.mutate({ email_tone: tone })}
          />
          <DeleteSeriesButton
            seriesName={series.name}
            disabled={remove.isPending}
            onConfirm={() => remove.mutate()}
          />
        </div>
      </section>

      <Tabs defaultValue="keyterms">
        <TabsList>
          <TabsTrigger value="keyterms">{t('tabs.glossary')}</TabsTrigger>
          <TabsTrigger value="suggested">{t('tabs.suggested')}</TabsTrigger>
          <TabsTrigger value="speakers">{t('tabs.speakers')}</TabsTrigger>
        </TabsList>
        <TabsContent value="keyterms" className="pt-3">
          <KeytermsList seriesId={seriesId} source="active" />
        </TabsContent>
        <TabsContent value="suggested" className="pt-3">
          <KeytermsList seriesId={seriesId} source="suggested" />
        </TabsContent>
        <TabsContent value="speakers" className="pt-3">
          <SpeakerNamesList seriesId={seriesId} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function SeriesNameField({ series, onSave }) {
  const { t } = useTranslation('meetings_series')
  const [value, setValue] = useState(series.name)
  return (
    <div className="space-y-1.5">
      <label className="block text-[13px] font-semibold text-foreground">
        {t('form.nameLabel')}
      </label>
      <div className="flex gap-2">
        <Input
          dir="auto"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button
          variant="outline"
          onClick={() => onSave(value.trim())}
          disabled={!value.trim() || value.trim() === series.name}
          className="h-[42px]"
        >
          {t('form.save')}
        </Button>
      </div>
    </div>
  )
}

function ToneSelector({ value, onChange }) {
  const { t } = useTranslation('meetings_series')
  const TONES = [
    { id: 'formal', label: t('form.toneFormal') },
    { id: 'casual', label: t('form.toneCasual') },
  ]
  return (
    <div className="space-y-1.5">
      <label className="block text-[13px] font-semibold text-foreground">
        {t('form.toneLabel')}
      </label>
      <div
        role="group"
        aria-label={t('form.toneLabel')}
        className="inline-flex h-[42px] items-center rounded-[11px] border border-border bg-background-secondary p-1"
      >
        {TONES.map((tone) => (
          <button
            key={tone.id}
            type="button"
            onClick={() => onChange(tone.id)}
            aria-pressed={value === tone.id}
            className={cn(
              'rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              value === tone.id
                ? 'bg-background text-foreground shadow-card'
                : 'text-foreground-secondary hover:text-foreground'
            )}
          >
            {tone.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function DeleteSeriesButton({ seriesName, disabled, onConfirm }) {
  const { t } = useTranslation('meetings_series')
  return (
    <div className="flex items-end self-end">
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            variant="outline"
            disabled={disabled}
            className="h-[42px]"
          >
            <Trash2 className="size-4 text-error" />
            <span>{t('form.delete')}</span>
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('form.deleteTitle', { name: seriesName })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('form.deleteDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('form.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={onConfirm}
              disabled={disabled}
              className="bg-error hover:bg-error/90"
            >
              {disabled ? t('form.deleting') : t('form.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function KeytermsList({ seriesId, source }) {
  const { t } = useTranslation('meetings_series')
  const qc = useQueryClient()
  const [newTerm, setNewTerm] = useState('')

  const manualQ = useQuery({
    queryKey: ['keyterms', seriesId, 'manual'],
    queryFn: () => listKeyterms(seriesId, 'manual'),
    enabled: source === 'active',
    staleTime: 30_000,
  })
  const acceptedQ = useQuery({
    queryKey: ['keyterms', seriesId, 'accepted'],
    queryFn: () => listKeyterms(seriesId, 'accepted'),
    enabled: source === 'active',
    staleTime: 30_000,
  })
  const suggestedQ = useQuery({
    queryKey: ['keyterms', seriesId, 'suggested'],
    queryFn: () => listKeyterms(seriesId, 'suggested'),
    enabled: source === 'suggested',
    staleTime: 30_000,
  })

  const add = useMutation({
    mutationFn: () => addKeyterm(seriesId, newTerm.trim()),
    onSuccess: () => {
      setNewTerm('')
      qc.invalidateQueries({ queryKey: ['keyterms', seriesId] })
      toast.success(t('keyterms.added'))
    },
    onError: (e) => toast.error(errMsg(e, t('errors.addTerm'))),
  })

  const accept = useMutation({
    mutationFn: (id) => acceptKeyterm(seriesId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['keyterms', seriesId] }),
    onError: (e) => toast.error(errMsg(e, t('errors.accept'))),
  })

  const reject = useMutation({
    mutationFn: (id) => rejectKeyterm(seriesId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['keyterms', seriesId] }),
    onError: (e) => toast.error(errMsg(e, t('errors.reject'))),
  })

  if (source === 'suggested') {
    if (suggestedQ.isLoading) {
      return (
        <div
          className="space-y-2 rounded-xl border border-border bg-background-elevated p-4"
          aria-busy="true"
          aria-live="polite"
        >
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-9 rounded-lg animate-shimmer" />
          ))}
        </div>
      )
    }
    if (suggestedQ.isError) {
      return (
        <EmptyState
          icon={AlertTriangle}
          tone="destructive"
          title={t('errors.loadSuggestions')}
        >
          <Button
            variant="outline"
            size="sm"
            onClick={() => suggestedQ.refetch()}
            className="mt-1 h-8 border-border"
          >
            {t('errors.retry')}
          </Button>
        </EmptyState>
      )
    }
    const items = suggestedQ.data ?? []
    if (items.length === 0) {
      return (
        <div className="rounded-xl border border-border bg-background-elevated px-5 py-8 text-center text-sm text-foreground-tertiary">
          {t('empty.noSuggestions')}
        </div>
      )
    }
    return (
      <div className="space-y-2 rounded-xl border border-border bg-background-elevated p-4">
        {items.map((item) => {
          const id = item._id ?? item.id
          const acceptPending = accept.isPending && accept.variables === id
          const rejectPending = reject.isPending && reject.variables === id
          return (
            <div
              key={id}
              className="flex items-center justify-between rounded-lg border border-border-light bg-background-secondary px-3.5 py-2"
              dir={dirOf(item.term)}
            >
              <span className="text-sm text-foreground">{item.term}</span>
              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  variant="default"
                  onClick={() => accept.mutate(id)}
                  disabled={acceptPending || rejectPending}
                >
                  {t('keyterms.accept')}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => reject.mutate(id)}
                  disabled={acceptPending || rejectPending}
                >
                  {t('keyterms.reject')}
                </Button>
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  if (manualQ.isLoading || acceptedQ.isLoading) {
    return (
      <div
        className="space-y-3 rounded-xl border border-border bg-background-elevated p-5"
        aria-busy="true"
        aria-live="polite"
      >
        <div className="h-9 rounded-lg animate-shimmer" />
        <div className="h-16 rounded-lg animate-shimmer" />
      </div>
    )
  }

  if (manualQ.isError || acceptedQ.isError) {
    return (
      <EmptyState
        icon={AlertTriangle}
        tone="destructive"
        title={t('errors.loadKeyterms')}
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            manualQ.refetch()
            acceptedQ.refetch()
          }}
          className="mt-1 h-8 border-border"
        >
          {t('errors.retry')}
        </Button>
      </EmptyState>
    )
  }

  const manualItems = manualQ.data ?? []
  const acceptedItems = acceptedQ.data ?? []

  return (
    <div className="space-y-5 rounded-xl border border-border bg-background-elevated p-5">
      <div className="flex gap-2">
        <Input
          dir="auto"
          value={newTerm}
          onChange={(e) => setNewTerm(e.target.value)}
          placeholder={t('keyterms.addPlaceholder')}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && newTerm.trim()) add.mutate()
          }}
        />
        <Button
          onClick={() => add.mutate()}
          disabled={!newTerm.trim() || add.isPending}
          className="h-[42px]"
        >
          <Plus className="size-4" />
          <span>{t('keyterms.add')}</span>
        </Button>
      </div>
      <KeytermGroup
        label={t('keyterms.manual')}
        items={manualItems}
        toneClass="bg-background-tertiary text-foreground border-border"
        onRemove={(id) => reject.mutate(id)}
        pendingId={reject.isPending ? reject.variables : null}
      />
      <KeytermGroup
        label={t('keyterms.accepted')}
        items={acceptedItems}
        toneClass="bg-success/10 text-success border-success/30"
        onRemove={(id) => reject.mutate(id)}
        pendingId={reject.isPending ? reject.variables : null}
      />
    </div>
  )
}

function KeytermGroup({ label, items, toneClass, onRemove, pendingId }) {
  const { t } = useTranslation('meetings_series')
  return (
    <div className="space-y-1.5">
      <p className="text-[13px] font-semibold text-foreground">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {items.length === 0 ? (
          <span className="text-xs text-foreground-tertiary">{t('keyterms.empty')}</span>
        ) : (
          items.map((item) => {
            const id = item._id ?? item.id
            return (
              <button
                key={id}
                type="button"
                onClick={() => onRemove(id)}
                disabled={pendingId === id}
                title={t('keyterms.removeHint')}
                aria-label={`${t('keyterms.reject')}: ${item.term}`}
                dir={dirOf(item.term)}
                className={cn(
                  'group inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs transition-opacity hover:opacity-80 disabled:opacity-50',
                  toneClass
                )}
              >
                <span>{item.term}</span>
                <X className="size-3 opacity-60" />
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}

function SpeakerNamesList({ seriesId }) {
  const { t } = useTranslation('meetings_series')
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['speaker-names', seriesId],
    queryFn: () => listSeriesSpeakerNames(seriesId),
  })
  if (isLoading) {
    return (
      <div
        className="rounded-xl border border-border bg-background-elevated p-5"
        aria-busy="true"
        aria-live="polite"
      >
        <div className="flex flex-wrap gap-1.5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-6 w-20 rounded-full animate-shimmer" />
          ))}
        </div>
      </div>
    )
  }
  if (isError) {
    return (
      <EmptyState
        icon={AlertTriangle}
        tone="destructive"
        title={t('errors.loadSpeakers')}
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          className="mt-1 h-8 border-border"
        >
          {t('errors.retry')}
        </Button>
      </EmptyState>
    )
  }
  const items = data ?? []
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-background-elevated px-5 py-8 text-center text-sm leading-7 text-foreground-tertiary">
        {t('empty.noSpeakers')}
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-border bg-background-elevated p-5">
      <div className="flex flex-wrap gap-1.5">
        {items.map((name) => (
          <span
            key={name}
            dir={dirOf(name)}
            className="rounded-full border border-border bg-background-secondary px-2.5 py-0.5 text-xs text-foreground-secondary"
          >
            {name}
          </span>
        ))}
      </div>
    </div>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
  Sparkles,
  UploadCloud,
  Loader2,
  X,
  Paperclip,
  BookOpen,
  Check,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { IconTile } from '@/components/ui/icon-tile'
import { uploadPayrollFile } from '@/services/payrollService'
import { knowledgeService } from '@/services/knowledgeService'
import { cn } from '@/lib/utils'

// Shared upload endpoint (POST /uploads/file -> { upload: { id } }). The payroll
// helper already unwraps `.upload`, so it returns `{ id }` — reuse it instead of
// duplicating the multipart POST.
const SLIDE_COUNTS = [6, 8, 10, 12, 15, 20]
const TONES = ['professional', 'friendly', 'persuasive', 'academic', 'playful']
const AUDIENCES = ['general', 'executives', 'students', 'engineers', 'investors']
const LANGUAGES = ['fa', 'en']
const THEMES = ['polymind', 'dark', 'minimal', 'vibrant', 'board', 'pitch', 'marketing', 'mono']

/**
 * BriefStep — stage 1. Collects the deck brief and kicks the outline SSE.
 *
 * Topic (required) + options (slide count / tone / audience / language / theme)
 * + optional source files (uploaded via the shared /uploads/file endpoint) and
 * Knowledge Vault items. The Generate button is disabled until a topic is
 * present and no upload is in flight.
 */
export default function BriefStep({ onStart }) {
  const { t } = useTranslation('presentations')

  const [topic, setTopic] = useState('')
  const [slideCount, setSlideCount] = useState(10)
  const [tone, setTone] = useState('professional')
  const [audience, setAudience] = useState('general')
  const [language, setLanguage] = useState('fa')
  const [theme, setTheme] = useState('polymind')
  const [generateImages, setGenerateImages] = useState(true)

  // [{ id, name }] for uploaded source files.
  const [uploads, setUploads] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(false)

  // Selected Knowledge Vault item ids.
  const [knowledgeIds, setKnowledgeIds] = useState([])

  const fileInputRef = useRef(null)
  const aliveRef = useRef(true)
  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  // One-shot tender handoff: sessionStorage.presentation_brief_prefill
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem('presentation_brief_prefill')
      if (!raw) return
      sessionStorage.removeItem('presentation_brief_prefill')
      const pre = JSON.parse(raw)
      if (pre?.topic) setTopic(String(pre.topic))
      if (pre?.language === 'en' || pre?.language === 'fa') setLanguage(pre.language)
      if (pre?.audience) setAudience(String(pre.audience))
      if (pre?.notes_markdown) {
        setTopic((prev) => {
          const base = prev || String(pre.topic || '')
          return base
        })
        // Append notes into topic if empty notes field — topic is the only free text.
        // Prefer combining topic + notes for outline quality.
        const notes = String(pre.notes_markdown).slice(0, 4000)
        setTopic((prev) => {
          const head = (prev || String(pre.topic || '')).trim()
          return head ? `${head}\n\n${notes}` : notes
        })
      }
    } catch {
      /* ignore bad prefill */
    }
  }, [])

  // First page of the caller's knowledge items for the optional source picker.
  const { data: knowledgeData, isError: knowledgeError } = useQuery({
    queryKey: ['knowledge', { presentationsPicker: true }],
    queryFn: () => knowledgeService.list({ page: 1, limit: 50 }),
    staleTime: 60 * 1000,
  })
  const knowledgeItems = Array.isArray(knowledgeData?.items) ? knowledgeData.items : []

  const handleFilePick = useCallback(async (e) => {
    const picked = Array.from(e.target.files || [])
    // Allow re-picking the same file later (onChange won't fire otherwise).
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (picked.length === 0) return

    setUploadError(false)
    setUploading(true)
    try {
      const results = await Promise.all(
        picked.map(async (file) => {
          const upload = await uploadPayrollFile(file)
          const id = upload?.id
          return id ? { id, name: file.name } : null
        }),
      )
      if (!aliveRef.current) return
      const ok = results.filter(Boolean)
      if (ok.length < picked.length) setUploadError(true)
      // Dedupe by id (a re-pick of an already-attached file).
      setUploads((prev) => {
        const seen = new Set(prev.map((u) => u.id))
        return [...prev, ...ok.filter((u) => !seen.has(u.id))]
      })
    } catch {
      if (aliveRef.current) setUploadError(true)
    } finally {
      if (aliveRef.current) setUploading(false)
    }
  }, [])

  const removeUpload = useCallback((id) => {
    setUploads((prev) => prev.filter((u) => u.id !== id))
  }, [])

  const toggleKnowledge = useCallback((id) => {
    setKnowledgeIds((prev) =>
      prev.includes(id) ? prev.filter((k) => k !== id) : [...prev, id],
    )
  }, [])

  const topicTrimmed = topic.trim()
  const canGenerate = topicTrimmed.length > 0 && !uploading

  const handleGenerate = useCallback(() => {
    if (!canGenerate) return
    onStart({
      topic: topicTrimmed,
      slide_count: slideCount,
      tone,
      audience,
      language,
      theme,
      upload_ids: uploads.map((u) => u.id),
      knowledge_ids: knowledgeIds,
      generate_images: generateImages,
    })
  }, [
    canGenerate,
    onStart,
    topicTrimmed,
    slideCount,
    tone,
    audience,
    language,
    theme,
    uploads,
    knowledgeIds,
    generateImages,
  ])

  return (
    <div className="space-y-6" dir="rtl">
      {/* ── Topic ── */}
      <section className="space-y-2">
        <Label htmlFor="presentation-topic" className="text-foreground-secondary">
          {t('brief.topic')}
        </Label>
        <Textarea
          id="presentation-topic"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder={t('brief.topicPlaceholder')}
          rows={4}
          dir="auto"
          className="min-h-28"
        />
      </section>

      {/* ── Options ── */}
      <section className="grid gap-4 sm:grid-cols-2">
        <OptionSelect
          id="presentation-slide-count"
          label={t('brief.slideCount')}
          value={String(slideCount)}
          onValueChange={(v) => setSlideCount(Number(v))}
          options={SLIDE_COUNTS.map((n) => ({ value: String(n), label: String(n) }))}
          numeric
        />
        <OptionSelect
          id="presentation-tone"
          label={t('brief.tone')}
          value={tone}
          onValueChange={setTone}
          options={TONES.map((v) => ({ value: v, label: t(`tones.${v}`) }))}
        />
        <OptionSelect
          id="presentation-audience"
          label={t('brief.audience')}
          value={audience}
          onValueChange={setAudience}
          options={AUDIENCES.map((v) => ({ value: v, label: t(`audiences.${v}`) }))}
        />
        <OptionSelect
          id="presentation-language"
          label={t('brief.language')}
          value={language}
          onValueChange={setLanguage}
          options={LANGUAGES.map((v) => ({ value: v, label: t(`languages.${v}`) }))}
        />
        <OptionSelect
          id="presentation-theme"
          label={t('brief.theme')}
          value={theme}
          onValueChange={setTheme}
          options={THEMES.map((v) => ({ value: v, label: t(`themes.${v}`) }))}
        />
      </section>

      {/* ── Generate-images toggle ── */}
      <section className="flex items-center justify-between gap-4 rounded-xl border border-border bg-background-secondary/30 px-4 py-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">{t('brief.generateImages')}</p>
          <p className="mt-0.5 text-xs text-foreground-tertiary">{t('brief.generateImagesHint')}</p>
        </div>
        <Switch
          checked={generateImages}
          onCheckedChange={setGenerateImages}
          aria-label={t('brief.generateImages')}
        />
      </section>

      {/* ── Source files (optional) ── */}
      <section className="space-y-2">
        <Label className="text-foreground-secondary">{t('brief.sources')}</Label>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFilePick}
          className="sr-only"
          aria-hidden="true"
          tabIndex={-1}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className={cn(
            'group flex w-full items-center gap-3 rounded-xl border border-dashed border-border bg-background-secondary p-4 text-start transition-colors',
            'hover:border-accent/50 hover:bg-accent/5',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
            'disabled:cursor-wait disabled:opacity-70',
          )}
          aria-busy={uploading}
        >
          <IconTile
            icon={uploading ? Loader2 : UploadCloud}
            tone="sky"
            size="md"
            iconClassName={uploading ? 'animate-spin' : undefined}
          />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">
              {uploading ? t('brief.uploading') : t('brief.addSources')}
            </p>
            <p className="mt-0.5 text-xs text-foreground-tertiary">{t('brief.sourcesHint')}</p>
          </div>
        </button>

        {uploadError && (
          <p className="text-xs text-error" dir="auto">
            {t('brief.uploadError')}
          </p>
        )}

        {uploads.length > 0 && (
          <ul className="flex flex-wrap gap-2">
            {uploads.map((u) => (
              <li
                key={u.id}
                className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-background-secondary px-3 py-1 text-xs text-foreground-secondary"
              >
                <Paperclip className="h-3 w-3 shrink-0" aria-hidden="true" />
                <span className="truncate" dir="auto">
                  {u.name}
                </span>
                <button
                  type="button"
                  onClick={() => removeUpload(u.id)}
                  className="shrink-0 rounded-full p-0.5 text-foreground-tertiary transition-colors hover:bg-background-tertiary hover:text-foreground"
                  aria-label={t('brief.removeSource')}
                >
                  <X className="h-3 w-3" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── Knowledge Vault (optional) ── */}
      {/* Render on items OR a fetch error so a failed load is distinguishable
          from "no saved items" (a silently hidden section reads as empty). */}
      {(knowledgeItems.length > 0 || knowledgeError) && (
        <section className="space-y-2">
          <Label className="text-foreground-secondary">{t('brief.knowledge')}</Label>
          <p className="text-xs text-foreground-tertiary">{t('brief.knowledgeHint')}</p>
          {knowledgeError ? (
            <p className="text-xs text-error" dir="auto">
              {t('brief.knowledgeError')}
            </p>
          ) : (
          <ul className="flex flex-wrap gap-2">
            {knowledgeItems.map((item) => {
              const selected = knowledgeIds.includes(item._id)
              return (
                <li key={item._id}>
                  <button
                    type="button"
                    onClick={() => toggleKnowledge(item._id)}
                    aria-pressed={selected}
                    className={cn(
                      'inline-flex max-w-[16rem] items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors',
                      selected
                        ? 'border-accent/50 bg-accent/10 text-accent'
                        : 'border-border bg-background-secondary text-foreground-secondary hover:bg-background-tertiary hover:text-foreground',
                    )}
                  >
                    {selected ? (
                      <Check className="h-3 w-3 shrink-0" aria-hidden="true" />
                    ) : (
                      <BookOpen className="h-3 w-3 shrink-0" aria-hidden="true" />
                    )}
                    <span className="truncate" dir="auto">
                      {item.title || t('brief.untitledKnowledge')}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
          )}
        </section>
      )}

      {/* ── Generate ── */}
      <div className="pt-2">
        <Button onClick={handleGenerate} disabled={!canGenerate} animated className="w-full sm:w-auto">
          <Sparkles className="me-2 h-4 w-4" aria-hidden="true" />
          {t('brief.generate')}
        </Button>
      </div>
    </div>
  )
}

/* ── Labeled Select field (repo Select primitive, not a raw <select>) ── */
function OptionSelect({ id, label, value, onValueChange, options, numeric = false }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-foreground-secondary">
        {label}
      </Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger id={id} aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {/* slide-count values are numeric — keep them ltr so Persian
                  digit shaping doesn't reorder them. */}
              <span dir={numeric ? 'ltr' : undefined}>{opt.label}</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

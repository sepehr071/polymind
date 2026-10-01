import { useMemo, useState } from 'react'
import {
  ChevronDown,
  Copy,
  Download,
  Handshake,
  Loader2,
  Mail,
  Sparkles,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { displayPrivacyForPath } from '@/constants/modelPrivacy'
import useEmailWriterFlow from '@/hooks/useEmailWriterFlow'
import useLocalAiStatus from '@/hooks/useLocalAiStatus'
import { cn } from '@/lib/utils'

const EXTRA_FIELDS = {
  official_letter: ['ref_number', 'date_shamsi'],
  invitation: ['event_time', 'event_place'],
  request: ['deadline'],
  resignation: ['last_day'],
  follow_up: ['prior_context'],
  reply: ['prior_context'],
}

/** Optional keys folded under "More options" (not recipient/points). */
const ALWAYS_OPTIONAL = [
  'subject',
  'sender_name',
  'sender_title',
  'org',
  'extra',
  // lang/tone counted separately via hook state
]

function Field({ label, required, requiredLabel, children, hint }) {
  return (
    <div className="space-y-1">
      <label className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <span>{label}</span>
        {required && (
          <span className="rounded-md bg-bg-3 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground/90">
            {requiredLabel}
          </span>
        )}
      </label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground/80">{hint}</p>}
    </div>
  )
}

function SegButton({ active, onClick, children, disabled }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
        active
          ? 'border-accent bg-accent/10 text-accent'
          : 'border-border/60 text-muted-foreground hover:border-accent/40 hover:text-foreground',
        disabled && 'opacity-50 pointer-events-none',
      )}
    >
      {children}
    </button>
  )
}

function countOptionalFilled(fields, templateId, lang, tone) {
  const keys = [...ALWAYS_OPTIONAL, ...(EXTRA_FIELDS[templateId] || [])]
  let n = 0
  for (const k of keys) {
    if (String(fields[k] || '').trim()) n += 1
  }
  // Non-default lang/tone count as "set" so badge reflects intentional choices
  if (lang && lang !== 'fa') n += 1
  if (tone && tone !== 'formal') n += 1
  return n
}

export default function EmailWriterPage() {
  const { t } = useTranslation('emailWriter')
  const f = useEmailWriterFlow()
  const { available: localAi, isLoading: localAiLoading } = useLocalAiStatus()
  const privacyMode = displayPrivacyForPath('/email-writer', {
    localAvailable: localAi,
    localStatusKnown: !localAiLoading,
  })
  const [moreOpen, setMoreOpen] = useState(false)
  const extra = EXTRA_FIELDS[f.templateId] || []
  const canGenerate = !!(f.fields.recipient?.trim() && f.fields.points?.trim()) && !f.running
  const requiredLabel = t('required')
  const optionalCount = useMemo(
    () => countOptionalFilled(f.fields, f.templateId, f.lang, f.tone),
    [f.fields, f.templateId, f.lang, f.tone],
  )

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(f.draft || '')
      toast.success(t('copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  const download = () => {
    const blob = new Blob([f.draft || ''], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'letter.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <PageShell width="wide">
      <PageHeader
        icon={Mail}
        title={t('title')}
        subtitle={t('subtitle')}
        actions={<PrivacyBadge mode={privacyMode} />}
      />
      <PrivacyBanner mode={privacyMode} />
      {f.error && (
        <div className="rounded-xl border border-error/30 bg-error/5 px-4 py-3 text-sm text-error" role="alert">
          {String(f.error)}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
        <Card className="p-4 space-y-4">
          {/* Template chips */}
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">{t('template')}</p>
            <div className="flex flex-wrap gap-1.5">
              {f.templates.map((id) => {
                const active = f.templateId === id
                return (
                  <button
                    key={id}
                    type="button"
                    disabled={f.running}
                    aria-pressed={active}
                    title={t(`templateDesc.${id}`)}
                    onClick={() => f.setTemplateId(id)}
                    className={cn(
                      'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                      active
                        ? 'border-accent bg-accent/10 text-accent shadow-sm'
                        : 'border-border/60 text-muted-foreground hover:border-accent/40 hover:text-foreground',
                      f.running && 'opacity-60 pointer-events-none',
                    )}
                  >
                    {t(`templates.${id}`)}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Essentials */}
          <Field label={t('fields.recipient')} required requiredLabel={requiredLabel} hint={t('hints.recipient')}>
            <Input
              value={f.fields.recipient}
              onChange={(e) => f.setField('recipient', e.target.value)}
              disabled={f.running}
              placeholder={t('placeholders.recipient')}
              dir="auto"
            />
          </Field>

          <Field label={t('fields.points')} required requiredLabel={requiredLabel} hint={t('hints.points')}>
            <Textarea
              rows={6}
              value={f.fields.points}
              onChange={(e) => f.setField('points', e.target.value)}
              disabled={f.running}
              placeholder={t('placeholders.points')}
              dir="auto"
            />
          </Field>

          {/* More options */}
          <Collapsible open={moreOpen} onOpenChange={setMoreOpen}>
            <CollapsibleTrigger
              type="button"
              className={cn(
                'group flex w-full items-center justify-between gap-2 rounded-xl border border-border/50',
                'bg-bg-3/30 px-3 py-2.5 text-start text-sm transition-colors',
                'hover:border-accent/30 hover:bg-bg-3/50',
              )}
            >
              <span className="flex min-w-0 items-center gap-2">
                <ChevronDown
                  className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180"
                  aria-hidden
                />
                <span className="font-medium">{t('moreOptions')}</span>
                <span className="text-xs text-muted-foreground">{t('moreOptionsOptional')}</span>
                {optionalCount > 0 && (
                  <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent">
                    {t('moreOptionsSet', { count: optionalCount })}
                  </span>
                )}
              </span>
            </CollapsibleTrigger>
            <CollapsibleContent className="space-y-4 pt-3">
              {extra.length > 0 && (
                <div className="space-y-3">
                  {extra.map((k) => (
                    <Field key={k} label={t(`fields.${k}`)}>
                      {k === 'prior_context' ? (
                        <Textarea
                          rows={3}
                          value={f.fields[k]}
                          onChange={(e) => f.setField(k, e.target.value)}
                          disabled={f.running}
                          dir="auto"
                        />
                      ) : (
                        <Input
                          value={f.fields[k]}
                          onChange={(e) => f.setField(k, e.target.value)}
                          disabled={f.running}
                          dir="auto"
                        />
                      )}
                    </Field>
                  ))}
                </div>
              )}

              <Field label={t('fields.subject')} hint={t('hints.subject')}>
                <Input
                  value={f.fields.subject}
                  onChange={(e) => f.setField('subject', e.target.value)}
                  disabled={f.running}
                  placeholder={t('placeholders.subject')}
                  dir="auto"
                />
              </Field>

              <div className="flex flex-wrap gap-4">
                <div className="space-y-1.5">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    {t('langLabel')}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {['fa', 'en'].map((code) => (
                      <SegButton
                        key={code}
                        active={f.lang === code}
                        disabled={f.running}
                        onClick={() => f.setLang(code)}
                      >
                        {t(`lang.${code}`)}
                      </SegButton>
                    ))}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    {t('toneLabel')}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {['formal', 'semi_formal', 'friendly'].map((tone) => (
                      <SegButton
                        key={tone}
                        active={f.tone === tone}
                        disabled={f.running}
                        onClick={() => f.setTone(tone)}
                      >
                        {t(`tone.${tone}`)}
                      </SegButton>
                    ))}
                  </div>
                </div>
              </div>

              <div className="space-y-3 border-t border-border/40 pt-3">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {t('section.from')}
                </p>
                <div className="grid gap-3 sm:grid-cols-2">
                  {['sender_name', 'sender_title'].map((k) => (
                    <Field key={k} label={t(`fields.${k}`)}>
                      <Input
                        value={f.fields[k]}
                        onChange={(e) => f.setField(k, e.target.value)}
                        disabled={f.running}
                        dir="auto"
                      />
                    </Field>
                  ))}
                </div>
                <Field label={t('fields.org')}>
                  <Input
                    value={f.fields.org}
                    onChange={(e) => f.setField('org', e.target.value)}
                    disabled={f.running}
                    dir="auto"
                  />
                </Field>
              </div>

              <Field label={t('fields.extra')} hint={t('hints.extra')}>
                <Textarea
                  rows={2}
                  value={f.fields.extra}
                  onChange={(e) => f.setField('extra', e.target.value)}
                  disabled={f.running}
                  placeholder={t('placeholders.extra')}
                  dir="auto"
                />
              </Field>
            </CollapsibleContent>
          </Collapsible>

          <div className="sticky bottom-3 z-10 flex flex-col gap-2 rounded-xl border border-border/60 bg-bg-2/95 p-3 shadow-md backdrop-blur-sm sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-muted-foreground">
              {!canGenerate && !f.running
                ? t('needRequired')
                : f.running
                  ? t('generating')
                  : t('ready')}
            </p>
            <Button onClick={f.generate} disabled={!canGenerate} className="w-full sm:w-auto">
              {f.running ? <Loader2 className="h-4 w-4 animate-spin me-2" /> : <Sparkles className="h-4 w-4 me-2" />}
              {f.running ? t('generating') : t('generate')}
            </Button>
          </div>
        </Card>

        {/* Preview */}
        <Card className="p-4 space-y-3 min-h-[24rem] lg:sticky lg:top-16">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold">{t('draft')}</p>
              <p className="text-[11px] text-muted-foreground">{t('draftHint')}</p>
            </div>
            <div className="flex gap-1">
              <Button type="button" size="icon" variant="ghost" onClick={copy} disabled={!f.draft} aria-label={t('copy')}>
                <Copy className="h-4 w-4" />
              </Button>
              <Button type="button" size="icon" variant="ghost" onClick={download} disabled={!f.draft} aria-label={t('download')}>
                <Download className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {f.running && !f.draft && (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <Loader2 className="h-8 w-8 animate-spin text-accent" />
              <p className="text-sm font-medium">{t('generating')}</p>
              <p className="text-xs text-muted-foreground max-w-xs">{t('generatingHint')}</p>
            </div>
          )}

          {f.draft ? (
            <div className="prose prose-sm dark:prose-invert max-w-none rounded-xl border border-border/40 bg-bg-0/40 p-4" dir="auto">
              <MarkdownRenderer content={f.draft} />
            </div>
          ) : !f.running ? (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center px-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/10 text-accent">
                <Handshake className="h-7 w-7" />
              </div>
              <p className="text-sm font-medium">{t('draftEmpty')}</p>
              <p className="text-xs text-muted-foreground max-w-sm">{t('draftEmptyHint')}</p>
            </div>
          ) : null}
        </Card>
      </div>
      {f.budgetModal}
      {f.dlpModal}
    </PageShell>
  )
}

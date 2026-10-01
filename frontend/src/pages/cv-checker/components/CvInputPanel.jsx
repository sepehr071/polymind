import { useCallback, useRef } from 'react'
import { FileText, Loader2, Upload, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

function SegButton({ active, onClick, children, disabled }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
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

const PHASES = ['starting', 'extracting', 'analyzing']

export default function CvInputPanel({ f }) {
  const { t } = useTranslation('cvChecker')
  const cvRef = useRef(null)
  const jdRef = useRef(null)
  const busy = f.running || f.uploading

  const onCvDrop = useCallback(
    (e) => {
      e.preventDefault()
      e.stopPropagation()
      if (busy) return
      const file = e.dataTransfer?.files?.[0]
      if (file) f.addCv(file)
    },
    [busy, f],
  )

  const phase = f.status?.phase

  return (
    <Card className="p-4 sm:p-5 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {['screen', 'improve'].map((m) => (
          <SegButton key={m} active={f.mode === m} disabled={f.running} onClick={() => f.setMode(m)}>
            {t(`mode.${m}`)}
          </SegButton>
        ))}
        <select
          className="h-9 rounded-lg border border-border/60 bg-bg-2/50 px-2 text-sm ms-auto"
          value={f.lang}
          onChange={(e) => f.setLang(e.target.value)}
          disabled={f.running}
        >
          <option value="fa">{t('lang.fa')}</option>
          <option value="en">{t('lang.en')}</option>
        </select>
      </div>

      {/* CV dropzone */}
      <div>
        <p className="text-xs font-medium text-muted-foreground mb-1.5">{t('cvFile')}</p>
        {!f.cv ? (
          <div
            className={cn(
              'rounded-xl border border-dashed border-border/80 bg-bg-2/40 px-4 py-7 text-center transition-colors',
              !busy && 'hover:border-accent/50 cursor-pointer',
              busy && 'opacity-60',
            )}
            onDragOver={(e) => {
              e.preventDefault()
              e.stopPropagation()
            }}
            onDrop={onCvDrop}
            onClick={() => {
              if (!busy) cvRef.current?.click()
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if ((e.key === 'Enter' || e.key === ' ') && !busy) {
                e.preventDefault()
                cvRef.current?.click()
              }
            }}
          >
            <input
              ref={cvRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.doc,.png,.jpg,.jpeg,.webp"
              onChange={(e) => {
                f.addCv(e.target.files?.[0])
                e.target.value = ''
              }}
              disabled={busy}
            />
            <Upload className="mx-auto h-7 w-7 text-muted-foreground mb-2" aria-hidden />
            <p className="text-sm font-medium">{t('drop.title')}</p>
            <p className="text-xs text-muted-foreground mt-1">{t('drop.hint')}</p>
            {f.uploading && (
              <p className="text-xs text-muted-foreground mt-2 flex items-center justify-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                {t('drop.uploading')}
              </p>
            )}
          </div>
        ) : (
          <div className="inline-flex max-w-full items-center gap-2 rounded-full border border-border/60 bg-bg-2/60 px-3 py-1.5 text-sm">
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="truncate max-w-[16rem]" dir="auto">
              {f.cv.name}
            </span>
            <button
              type="button"
              className="rounded-full p-0.5 hover:bg-bg-3 disabled:opacity-40"
              onClick={() => f.setCv(null)}
              disabled={f.running}
              aria-label={t('remove')}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* JD */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">{t('jdText')}</label>
        <Textarea
          rows={4}
          value={f.jdText}
          onChange={(e) => f.setJdText(e.target.value)}
          disabled={f.running}
          placeholder={t('jdPlaceholder')}
          dir="auto"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => jdRef.current?.click()}
            disabled={busy}
          >
            <Upload className="h-3.5 w-3.5 me-1.5" />
            {f.jdFile ? f.jdFile.name : t('uploadJd')}
          </Button>
          <input
            ref={jdRef}
            type="file"
            className="hidden"
            accept=".pdf,.docx,.doc,.txt"
            onChange={(e) => {
              f.addJdFile(e.target.files?.[0])
              e.target.value = ''
            }}
          />
          {f.jdFile && (
            <button
              type="button"
              className="text-xs text-muted-foreground hover:text-foreground"
              onClick={() => f.setJdFile(null)}
              disabled={f.running}
            >
              <X className="inline h-3 w-3 me-0.5" />
              {t('remove')}
            </button>
          )}
        </div>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">{t('focus')}</label>
        <Textarea
          rows={2}
          value={f.focus}
          onChange={(e) => f.setFocus(e.target.value)}
          disabled={f.running}
          placeholder={t('focusPlaceholder')}
          dir="auto"
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={f.run} disabled={!f.cv || busy}>
          {f.running ? <Loader2 className="h-4 w-4 animate-spin me-2" /> : null}
          {t('run')}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={f.clearForm} disabled={f.running}>
          {t('clear')}
        </Button>
      </div>

      {phase && (
        <div className="flex flex-wrap gap-1.5" aria-live="polite">
          {PHASES.map((p) => {
            const active = phase === p
            const done = PHASES.indexOf(phase) > PHASES.indexOf(p)
            return (
              <span
                key={p}
                className={cn(
                  'rounded-full px-2.5 py-0.5 text-[11px] font-medium border',
                  active && 'border-accent bg-accent/10 text-accent',
                  done && 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
                  !active && !done && 'border-border/50 text-muted-foreground',
                )}
              >
                {active && <Loader2 className="inline h-3 w-3 animate-spin me-1" />}
                {t(`status.${p}`)}
              </span>
            )
          })}
        </div>
      )}
    </Card>
  )
}

import { useRef, useState } from 'react'
import { ChevronDown, Loader2, Upload, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Card } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { RESEARCH_STARTER_IDS } from '@/hooks/useResearchFlow'
import { cn } from '@/lib/utils'

const MODES = ['quick', 'deep', 'premium']

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

/**
 * Brief form: starters, mode cards, query, optional focus/files, run CTA.
 */
export default function ResearchBrief({
  query, setQuery,
  mode, setMode,
  lang, setLang,
  focus, setFocus,
  files, setFiles, addFiles,
  applyStarter,
  running, uploading,
  onRun,
  showStarters = true,
}) {
  const { t } = useTranslation('research')
  const inputRef = useRef(null)
  const [moreOpen, setMoreOpen] = useState(!!focus?.trim() || files.length > 0)
  const canAttach = mode === 'deep' || mode === 'premium'

  return (
    <div className="space-y-4">
      {showStarters && !query.trim() && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">{t('pitch')}</p>
          <p className="text-xs font-medium text-muted-foreground">{t('starters.label')}</p>
          <div className="flex flex-wrap gap-2">
            {RESEARCH_STARTER_IDS.map((id) => (
              <button
                key={id}
                type="button"
                disabled={running}
                onClick={() => applyStarter(id)}
                className={cn(
                  'rounded-full border border-border/60 bg-bg-2 px-3 py-1.5 text-xs font-medium',
                  'text-foreground/90 hover:border-accent/40 hover:bg-accent/5 transition-colors',
                  running && 'opacity-50 pointer-events-none',
                )}
              >
                {t(`starters.${id}.label`)}
              </button>
            ))}
          </div>
        </div>
      )}

      <Card className="p-4 space-y-4">
        <div className="grid gap-2 sm:grid-cols-3">
          {MODES.map((m) => {
            const active = mode === m
            return (
              <button
                key={m}
                type="button"
                disabled={running}
                onClick={() => setMode(m)}
                className={cn(
                  'rounded-xl border p-3 text-start transition-colors',
                  active
                    ? 'border-accent bg-accent/10 shadow-sm'
                    : 'border-border/60 hover:border-accent/30 hover:bg-bg-2',
                  running && 'opacity-60',
                )}
              >
                <p className={cn('text-sm font-semibold', active && 'text-accent')}>
                  {t(`mode.${m}`)}
                </p>
                <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
                  {t(`mode.${m}Desc`)}
                </p>
              </button>
            )
          })}
        </div>

        {mode === 'premium' && (
          <div
            className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-sm"
            role="alert"
          >
            {t('premiumWarn')}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground me-1">{t('langLabel')}</span>
          <SegButton active={lang === 'fa'} onClick={() => setLang('fa')} disabled={running}>
            {t('lang.fa')}
          </SegButton>
          <SegButton active={lang === 'en'} onClick={() => setLang('en')} disabled={running}>
            {t('lang.en')}
          </SegButton>
        </div>

        <div>
          <label className="text-xs font-medium text-muted-foreground" htmlFor="research-query">
            {t('query')}
          </label>
          <Textarea
            id="research-query"
            className="mt-1"
            rows={4}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={running}
            dir="auto"
            placeholder={t('queryPlaceholder')}
          />
        </div>

        <Collapsible open={moreOpen} onOpenChange={setMoreOpen}>
          <CollapsibleTrigger asChild>
            <button
              type="button"
              disabled={running}
              className={cn(
                'inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground',
                'hover:text-foreground transition-colors',
                running && 'opacity-50',
              )}
            >
              <ChevronDown
                className={cn('h-3.5 w-3.5 transition-transform', moreOpen && 'rotate-180')}
                aria-hidden
              />
              {t('moreOptions')}
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-3 space-y-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="research-focus">
                {t('focus')}
              </label>
              <Textarea
                id="research-focus"
                className="mt-1"
                rows={2}
                value={focus}
                onChange={(e) => setFocus(e.target.value)}
                disabled={running}
                dir="auto"
                placeholder={t('focusPlaceholder')}
              />
            </div>
            {canAttach && (
              <div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => inputRef.current?.click()}
                  disabled={running || uploading}
                >
                  {uploading ? (
                    <Loader2 className="h-4 w-4 animate-spin me-2" />
                  ) : (
                    <Upload className="h-4 w-4 me-2" />
                  )}
                  {t('attach')}
                </Button>
                <p className="mt-1 text-[11px] text-muted-foreground">{t('attachHint')}</p>
                <input
                  ref={inputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    addFiles(e.target.files)
                    e.target.value = ''
                  }}
                />
                {!!files.length && (
                  <ul className="flex flex-wrap gap-2 mt-2">
                    {files.map((file) => (
                      <li
                        key={file.upload_id}
                        className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs"
                      >
                        <span className="truncate max-w-[10rem]" dir="auto">{file.name}</span>
                        <button
                          type="button"
                          aria-label="Remove"
                          onClick={() => setFiles((p) => p.filter((x) => x.upload_id !== file.upload_id))}
                          disabled={running}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </CollapsibleContent>
        </Collapsible>

        <div className="flex flex-wrap gap-2 pt-1">
          <Button onClick={onRun} disabled={!query.trim() || running}>
            {running ? <Loader2 className="h-4 w-4 animate-spin me-2" /> : null}
            {running ? t('running') : t('run')}
          </Button>
        </div>
      </Card>
    </div>
  )
}

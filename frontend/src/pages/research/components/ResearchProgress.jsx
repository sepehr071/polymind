import { Loader2, Square } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

function formatElapsed(s) {
  const n = Math.max(0, Number(s) || 0)
  const m = Math.floor(n / 60)
  const r = n % 60
  return m > 0 ? `${m}:${String(r).padStart(2, '0')}` : `0:${String(r).padStart(2, '0')}`
}

function expectKey(mode) {
  if (mode === 'quick') return 'progress.expectQuick'
  if (mode === 'premium') return 'progress.expectPremium'
  return 'progress.expectDeep'
}

/**
 * Honest single-elapsed progress — no fake multi-step checklist.
 */
export default function ResearchProgress({
  mode,
  elapsedS,
  query,
  onCancel,
  className,
  backgroundSafe = false,
}) {
  const { t } = useTranslation('research')
  const q = (query || '').trim()

  return (
    <Card
      className={cn('p-6 sm:p-8 border-accent/20 bg-accent/[0.03]', className)}
      aria-live="polite"
      aria-busy="true"
    >
      <div className="flex flex-col items-center text-center gap-4 max-w-md mx-auto">
        <div className="relative flex h-14 w-14 items-center justify-center">
          <span
            className="absolute inset-0 rounded-full bg-accent/15 animate-pulse"
            aria-hidden
          />
          <Loader2 className="relative h-7 w-7 animate-spin text-accent" aria-hidden />
        </div>

        <div className="space-y-1">
          <p className="text-base font-semibold">{t('progress.title')}</p>
          <p className="text-sm text-muted-foreground">{t('progress.working')}</p>
          {q && (
            <p className="mt-2 text-xs text-muted-foreground/90 line-clamp-3" dir="auto">
              {q}
            </p>
          )}
        </div>

        <div className="space-y-0.5" dir="ltr">
          <p className="text-3xl font-semibold tabular-nums tracking-tight text-accent">
            {formatElapsed(elapsedS)}
          </p>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
            {t('progress.elapsed')}
          </p>
        </div>

        <p className="text-sm text-muted-foreground leading-relaxed">
          {t(expectKey(mode))}
        </p>
        <p className="text-xs text-muted-foreground/80">
          {t(backgroundSafe ? 'progress.stayBackground' : 'progress.stay')}
        </p>

        <div className="flex flex-col items-center gap-2 pt-2 w-full">
          <Button type="button" variant="outline" onClick={onCancel}>
            <Square className="h-3.5 w-3.5 me-2" />
            {t('cancel')}
          </Button>
          <p className="text-[11px] text-muted-foreground max-w-sm">{t('cancelHint')}</p>
        </div>
      </div>
    </Card>
  )
}

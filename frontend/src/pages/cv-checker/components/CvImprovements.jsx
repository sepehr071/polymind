import { Copy } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const PRI_ORDER = { high: 0, med: 1, low: 2 }
const PRI_CLASS = {
  high: 'bg-red-500/10 text-red-700 dark:text-red-300',
  med: 'bg-amber-500/15 text-amber-800 dark:text-amber-300',
  low: 'bg-bg-2 text-muted-foreground',
}

export default function CvImprovements({ improvements, rewrittenBullets, languageNotes }) {
  const { t } = useTranslation('cvChecker')
  const imps = Array.isArray(improvements)
    ? [...improvements].sort(
        (a, b) => (PRI_ORDER[a.priority] ?? 9) - (PRI_ORDER[b.priority] ?? 9),
      )
    : []
  const bullets = Array.isArray(rewrittenBullets) ? rewrittenBullets : []
  const notes = Array.isArray(languageNotes) ? languageNotes : []

  if (!imps.length && !bullets.length && !notes.length) return null

  const copyText = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('actions.copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  return (
    <div className="space-y-4">
      {!!imps.length && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold">{t('improvements')}</h3>
          <ul className="space-y-2">
            {imps.map((row, i) => {
              const pri = row.priority || 'med'
              return (
                <li
                  key={i}
                  className="rounded-lg border border-border/50 px-3 py-2.5 text-sm space-y-1"
                  dir="auto"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        'rounded-md px-1.5 py-0.5 text-[10px] font-medium',
                        PRI_CLASS[pri] || PRI_CLASS.med,
                      )}
                    >
                      {t(`priority.${pri}`, { defaultValue: pri })}
                    </span>
                    {row.section ? (
                      <span className="text-xs text-muted-foreground">{row.section}</span>
                    ) : null}
                  </div>
                  {row.issue ? <p className="font-medium">{row.issue}</p> : null}
                  {row.suggestion ? (
                    <p className="text-muted-foreground">{row.suggestion}</p>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {!!bullets.length && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold">{t('rewrites')}</h3>
          {bullets.map((b, i) => (
            <div
              key={i}
              className="rounded-lg border border-border/50 p-3 text-sm space-y-1.5"
              dir="auto"
            >
              {b.original ? (
                <p className="text-muted-foreground line-through text-xs">{b.original}</p>
              ) : null}
              <div className="flex items-start gap-2">
                <p className="flex-1 min-w-0">{b.improved}</p>
                {b.improved ? (
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="h-7 w-7 shrink-0"
                    onClick={() => copyText(b.improved)}
                    aria-label={t('actions.copyOne')}
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </Button>
                ) : null}
              </div>
            </div>
          ))}
        </section>
      )}

      {!!notes.length && (
        <section className="space-y-1.5">
          <h3 className="text-sm font-semibold">{t('languageNotes')}</h3>
          <ul className="list-disc ps-5 text-sm space-y-1" dir="auto">
            {notes.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

function barColor(score) {
  if (score == null) return 'bg-muted-foreground/30'
  if (score >= 70) return 'bg-emerald-500'
  if (score >= 50) return 'bg-amber-500'
  return 'bg-red-500/80'
}

export default function CvDimensions({ dimensions }) {
  const { t } = useTranslation('cvChecker')
  const list = Array.isArray(dimensions) ? dimensions : []
  if (!list.length) return null

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold">{t('dimensions')}</h3>
      <ul className="space-y-3">
        {list.map((d, i) => {
          const score = d.score != null ? Number(d.score) : null
          const pct = score != null ? Math.max(0, Math.min(100, score)) : 0
          return (
            <li key={d.id || i} className="space-y-1">
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="font-medium" dir="auto">
                  {d.label || d.id}
                </span>
                {score != null && (
                  <span className="tabular-nums text-muted-foreground text-xs">{score}</span>
                )}
              </div>
              <div className="h-1.5 rounded-full bg-bg-3 overflow-hidden">
                <div
                  className={cn('h-full rounded-full transition-[width]', barColor(score))}
                  style={{ width: `${pct}%` }}
                />
              </div>
              {d.notes ? (
                <p className="text-xs text-muted-foreground" dir="auto">
                  {d.notes}
                </p>
              ) : null}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

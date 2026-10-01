import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

const STATUS_CLASS = {
  met: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  partial: 'bg-amber-500/15 text-amber-800 dark:text-amber-300',
  missing: 'bg-red-500/10 text-red-700 dark:text-red-300',
}

export default function CvMustHaves({ items }) {
  const { t } = useTranslation('cvChecker')
  const list = Array.isArray(items) ? items : []
  if (!list.length) return null

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">{t('mustHaves')}</h3>
      <ul className="space-y-2">
        {list.map((row, i) => {
          const st = row.status || 'partial'
          const stLabel =
            st === 'met' ? t('statusMet') : st === 'missing' ? t('statusMissing') : t('statusPartial')
          return (
            <li
              key={i}
              className="flex flex-wrap items-start gap-2 rounded-lg border border-border/50 bg-bg-2/30 px-3 py-2 text-sm"
            >
              <span
                className={cn(
                  'shrink-0 rounded-md px-2 py-0.5 text-[11px] font-medium',
                  STATUS_CLASS[st] || STATUS_CLASS.partial,
                )}
              >
                {stLabel}
              </span>
              <div className="min-w-0 flex-1 space-y-0.5" dir="auto">
                <p className="font-medium">{row.item}</p>
                {row.evidence ? (
                  <p className="text-xs text-muted-foreground">{row.evidence}</p>
                ) : null}
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

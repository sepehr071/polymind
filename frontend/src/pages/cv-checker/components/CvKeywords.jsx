import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

function ChipList({ items, tone }) {
  if (!items?.length) return null
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((k, i) => (
        <li
          key={`${k}-${i}`}
          className={cn(
            'rounded-full px-2.5 py-0.5 text-xs font-medium border',
            tone === 'present'
              ? 'bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 border-emerald-500/25'
              : 'bg-bg-2 text-muted-foreground border-border/60',
          )}
          dir="auto"
        >
          {k}
        </li>
      ))}
    </ul>
  )
}

export default function CvKeywords({ keywords }) {
  const { t } = useTranslation('cvChecker')
  const present = Array.isArray(keywords?.present) ? keywords.present : []
  const missing = Array.isArray(keywords?.missing) ? keywords.missing : []
  if (!present.length && !missing.length) return null

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold">{t('keywords')}</h3>
      {!!present.length && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium text-muted-foreground">{t('keywordsPresent')}</p>
          <ChipList items={present} tone="present" />
        </div>
      )}
      {!!missing.length && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium text-muted-foreground">{t('keywordsMissing')}</p>
          <ChipList items={missing} tone="missing" />
        </div>
      )}
    </section>
  )
}

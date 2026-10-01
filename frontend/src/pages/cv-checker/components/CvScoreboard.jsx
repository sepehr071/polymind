import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

function scoreTone(n) {
  if (n == null || Number.isNaN(Number(n))) return 'bg-bg-2 text-muted-foreground'
  const v = Number(n)
  if (v >= 70) return 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
  if (v >= 50) return 'bg-amber-500/15 text-amber-800 dark:text-amber-300'
  return 'bg-red-500/10 text-red-700 dark:text-red-300'
}

const REC_CLASS = {
  advance: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
  maybe: 'bg-amber-500/15 text-amber-800 dark:text-amber-300 border-amber-500/30',
  pass: 'bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/30',
  n_a: 'bg-bg-2 text-muted-foreground border-border/50',
}

function ScorePill({ label, value }) {
  if (value == null) return null
  return (
    <div className={cn('rounded-xl border border-border/40 px-4 py-3 min-w-[6.5rem]', scoreTone(value))}>
      <p className="text-[11px] font-medium opacity-80">{label}</p>
      <p className="text-2xl font-semibold tabular-nums leading-tight mt-0.5">{value}</p>
    </div>
  )
}

export default function CvScoreboard({ result }) {
  const { t } = useTranslation('cvChecker')
  if (!result) return null
  const rec = result.recommendation || 'n_a'

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2 items-stretch">
        <ScorePill label={t('score')} value={result.overall_score} />
        <ScorePill label={t('match')} value={result.match_score} />
        {rec && (
          <div
            className={cn(
              'rounded-xl border px-4 py-3 min-w-[7rem] flex flex-col justify-center',
              REC_CLASS[rec] || REC_CLASS.n_a,
            )}
          >
            <p className="text-[11px] font-medium opacity-80">{t('recommendation')}</p>
            <p className="text-lg font-semibold mt-0.5">{t(`rec.${rec}`, { defaultValue: rec })}</p>
          </div>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground">{t('suggestionOnly')}</p>
    </div>
  )
}

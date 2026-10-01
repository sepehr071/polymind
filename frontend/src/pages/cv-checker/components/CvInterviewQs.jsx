import { Copy } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { interviewQuestionsText } from '@/utils/cvReportMarkdown'

export default function CvInterviewQs({ interviewQuestions, risksOrQuestions }) {
  const { t } = useTranslation('cvChecker')
  const structured = Array.isArray(interviewQuestions) ? interviewQuestions : []
  const fallback = Array.isArray(risksOrQuestions) ? risksOrQuestions : []

  if (!structured.length && !fallback.length) return null

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(
        interviewQuestionsText({
          interview_questions: structured,
          risks_or_questions: fallback,
        }),
      )
      toast.success(t('actions.copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  const copyOne = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('actions.copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t('questions')}</h3>
        <Button type="button" variant="ghost" size="sm" onClick={copyAll}>
          <Copy className="h-3.5 w-3.5 me-1" />
          {t('actions.copyQuestions')}
        </Button>
      </div>
      <ul className="space-y-2">
        {structured.length
          ? structured.map((q, i) => {
              const text = typeof q === 'string' ? q : q.question
              const why = typeof q === 'object' ? q.rationale : ''
              return (
                <li
                  key={i}
                  className="rounded-lg border border-border/50 bg-bg-2/20 px-3 py-2.5 text-sm space-y-1"
                >
                  <div className="flex items-start gap-2">
                    <span className="text-xs text-muted-foreground tabular-nums mt-0.5 shrink-0">
                      {i + 1}.
                    </span>
                    <p className="flex-1 min-w-0 font-medium" dir="auto">
                      {text}
                    </p>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 shrink-0"
                      onClick={() => copyOne(text)}
                      aria-label={t('actions.copyOne')}
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  {why ? (
                    <p className="text-xs text-muted-foreground ps-5" dir="auto">
                      <span className="font-medium">{t('rationale')}: </span>
                      {why}
                    </p>
                  ) : null}
                </li>
              )
            })
          : fallback.map((s, i) => (
              <li
                key={i}
                className="flex items-start gap-2 rounded-lg border border-border/50 px-3 py-2 text-sm"
              >
                <span className="text-xs text-muted-foreground tabular-nums mt-0.5">{i + 1}.</span>
                <p className="flex-1 min-w-0" dir="auto">
                  {s}
                </p>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 shrink-0"
                  onClick={() => copyOne(s)}
                  aria-label={t('actions.copyOne')}
                >
                  <Copy className="h-3.5 w-3.5" />
                </Button>
              </li>
            ))}
      </ul>
    </section>
  )
}

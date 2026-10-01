import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'

/**
 * Blocking clarify card — user must answer before the agent resumes.
 * questions: [{ id, prompt, options?: string[] }]
 */
export default function AgentClarifyCard({ questions = [], onSubmit, disabled }) {
  const { t } = useTranslation('agent')
  const list = useMemo(
    () => (Array.isArray(questions) ? questions.filter((q) => q?.id && q?.prompt) : []),
    [questions],
  )
  const [answers, setAnswers] = useState(() =>
    Object.fromEntries(list.map((q) => [q.id, ''])),
  )

  const allAnswered = list.every((q) => String(answers[q.id] || '').trim())

  if (!list.length) return null

  return (
    <div
      className={cn('rounded-xl p-4')}
      style={solidPanelSx({ radius: RADII.surface })}
    >
      <p className="mb-3 text-[13px] font-semibold text-foreground">
        {t('clarify.title', { defaultValue: 'A few clarifications' })}
      </p>
      <div className="flex flex-col gap-4">
        {list.map((q) => (
          <div key={q.id} className="flex flex-col gap-2">
            <label className="text-[13px] text-muted-foreground" htmlFor={`clarify-${q.id}`}>
              {q.prompt}
            </label>
            {Array.isArray(q.options) && q.options.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {q.options.map((opt) => {
                  const selected = answers[q.id] === opt
                  return (
                    <button
                      key={opt}
                      type="button"
                      disabled={disabled}
                      onClick={() => setAnswers((a) => ({ ...a, [q.id]: opt }))}
                      className={cn(
                        'rounded-full border px-3 py-1.5 text-[12px] transition-colors',
                        selected
                          ? 'border-primary bg-primary/15 text-primary'
                          : 'border-border/70 bg-bg-2/50 text-foreground hover:border-primary/40',
                      )}
                    >
                      {opt}
                    </button>
                  )
                })}
              </div>
            ) : null}
            <Input
              id={`clarify-${q.id}`}
              value={answers[q.id] || ''}
              disabled={disabled}
              onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
              placeholder={t('clarify.placeholder', { defaultValue: 'Your answer…' })}
              className="text-[13px]"
            />
          </div>
        ))}
      </div>
      <div className="mt-4 flex justify-end">
        <Button
          type="button"
          disabled={disabled || !allAnswered}
          onClick={() => onSubmit?.(answers)}
        >
          {t('clarify.submit', { defaultValue: 'Continue' })}
        </Button>
      </div>
    </div>
  )
}

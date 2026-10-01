import { AlertTriangle, FileUser } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { Card } from '@/components/ui/card'
import useCvCheckerFlow from '@/hooks/useCvCheckerFlow'
import CvInputPanel from './components/CvInputPanel'
import CvScoreboard from './components/CvScoreboard'
import CvMustHaves from './components/CvMustHaves'
import CvDimensions from './components/CvDimensions'
import CvKeywords from './components/CvKeywords'
import CvFindings from './components/CvFindings'
import CvInterviewQs from './components/CvInterviewQs'
import CvImprovements from './components/CvImprovements'
import CvResultActions from './components/CvResultActions'

export default function CvCheckerPage() {
  const { t } = useTranslation('cvChecker')
  const f = useCvCheckerFlow()
  const pack = f.result
  const r = pack?.result
  const isScreen = f.mode === 'screen'

  return (
    <PageShell width="standard">
      <PageHeader
        icon={FileUser}
        title={t('title')}
        subtitle={t('subtitle')}
        actions={<PrivacyBadge mode="cloud" />}
      />
      <PrivacyBanner mode="cloud" />

      <div
        className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm"
        role="note"
      >
        {t('disclaimer')}
      </div>

      {f.error && (
        <div
          className="flex gap-2 rounded-xl border border-error/30 bg-error/5 px-4 py-3 text-sm text-error"
          role="alert"
        >
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span dir="auto">{String(f.error)}</span>
        </div>
      )}

      <CvInputPanel f={f} />

      {r && (
        <Card className="p-4 sm:p-5 space-y-5">
          <CvResultActions
            result={r}
            pack={pack}
            mode={f.mode}
            onScreenAnother={f.screenAnother}
          />

          <CvScoreboard result={r} />

          {r.summary ? (
            <p className="text-sm leading-relaxed" dir="auto">
              {r.summary}
            </p>
          ) : null}

          <CvMustHaves items={r.must_have_checklist} />
          <CvDimensions dimensions={r.dimensions} />
          <CvKeywords keywords={r.keywords} />
          <CvFindings strengths={r.strengths} gaps={r.gaps} />

          {isScreen ||
          (Array.isArray(r.interview_questions) && r.interview_questions.length) ||
          (Array.isArray(r.risks_or_questions) && r.risks_or_questions.length) ? (
            <CvInterviewQs
              interviewQuestions={r.interview_questions}
              risksOrQuestions={r.risks_or_questions}
            />
          ) : null}

          <CvImprovements
            improvements={r.improvements}
            rewrittenBullets={r.rewritten_bullets}
            languageNotes={r.language_notes}
          />

          {r.bias_check?.note ? (
            <p className="text-xs text-muted-foreground" dir="auto">
              <span className="font-medium">{t('biasNote')}: </span>
              {r.bias_check.note}
            </p>
          ) : null}

          <p className="text-[11px] text-muted-foreground border-t border-border/40 pt-3">
            {pack.disclaimer || t('disclaimer')}
          </p>
        </Card>
      )}

      {f.budgetModal}
      {f.dlpModal}
    </PageShell>
  )
}

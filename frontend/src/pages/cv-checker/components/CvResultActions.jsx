import { Copy, Download, UserRoundPlus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { cvReportMarkdown, interviewQuestionsText } from '@/utils/cvReportMarkdown'

function labelsFromT(t) {
  return {
    title: t('title'),
    summary: t('summary'),
    score: t('score'),
    match: t('match'),
    recommendation: t('recommendation'),
    mustHaves: t('mustHaves'),
    dimensions: t('dimensions'),
    keywords: t('keywords'),
    keywordsPresent: t('keywordsPresent'),
    keywordsMissing: t('keywordsMissing'),
    strengths: t('strengths'),
    gaps: t('gaps'),
    questions: t('questions'),
    improvements: t('improvements'),
    rewrites: t('rewrites'),
    languageNotes: t('languageNotes'),
    rec_advance: t('rec.advance'),
    rec_maybe: t('rec.maybe'),
    rec_pass: t('rec.pass'),
    rec_n_a: t('rec.n_a'),
  }
}

export default function CvResultActions({ result, pack, onScreenAnother, mode }) {
  const { t } = useTranslation('cvChecker')
  const r = result

  const reportMd = () =>
    cvReportMarkdown(r, labelsFromT(t), {
      disclaimer: pack?.disclaimer || t('disclaimer'),
    })

  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(reportMd())
      toast.success(t('actions.copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  const copyQs = async () => {
    try {
      const text = interviewQuestionsText(r)
      if (!text) return
      await navigator.clipboard.writeText(text)
      toast.success(t('actions.copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  const download = () => {
    const blob = new Blob([reportMd()], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'cv-screening-note.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  const hasQs =
    (Array.isArray(r?.interview_questions) && r.interview_questions.length > 0) ||
    (Array.isArray(r?.risks_or_questions) && r.risks_or_questions.length > 0)

  return (
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant="outline" size="sm" onClick={copyReport}>
        <Copy className="h-3.5 w-3.5 me-1.5" />
        {t('actions.copyReport')}
      </Button>
      {hasQs && (
        <Button type="button" variant="outline" size="sm" onClick={copyQs}>
          <Copy className="h-3.5 w-3.5 me-1.5" />
          {t('actions.copyQuestions')}
        </Button>
      )}
      <Button type="button" variant="outline" size="sm" onClick={download}>
        <Download className="h-3.5 w-3.5 me-1.5" />
        {t('actions.download')}
      </Button>
      {mode === 'screen' && (
        <Button type="button" variant="secondary" size="sm" onClick={onScreenAnother}>
          <UserRoundPlus className="h-3.5 w-3.5 me-1.5" />
          {t('actions.screenAnother')}
        </Button>
      )}
    </div>
  )
}

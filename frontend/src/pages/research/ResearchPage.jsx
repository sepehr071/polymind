import { AlertTriangle, Telescope } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { Button } from '@/components/ui/button'
import useResearchFlow from '@/hooks/useResearchFlow'
import ResearchBrief from './components/ResearchBrief'
import ResearchProgress from './components/ResearchProgress'
import ResearchReport from './components/ResearchReport'

export default function ResearchPage() {
  const { t } = useTranslation('research')
  const f = useResearchFlow()

  const showBrief = f.stage === 'idle' || f.stage === 'failed'
  const showProgress = f.stage === 'running'
  const showReport = f.stage === 'done' && !!f.report

  return (
    <PageShell width={showReport ? 'wide' : 'standard'}>
      <PageHeader
        icon={Telescope}
        title={t('title')}
        subtitle={t('subtitle')}
        actions={<PrivacyBadge mode="cloud" />}
      />
      <PrivacyBanner mode="cloud" />

      {f.error && (f.stage === 'failed' || f.stage === 'idle') && (
        <div
          className="flex flex-wrap items-start gap-3 rounded-xl border border-error/30 bg-error/5 px-4 py-3 text-sm text-error"
          role="alert"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" aria-hidden />
          <span className="flex-1 min-w-0">{String(f.error)}</span>
          <div className="flex gap-2 shrink-0">
            <Button type="button" size="sm" variant="outline" onClick={f.retry}>
              {t('retry')}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => f.setError(null)}
            >
              {t('dismissError')}
            </Button>
          </div>
        </div>
      )}

      {showBrief && (
        <ResearchBrief
          query={f.query}
          setQuery={f.setQuery}
          mode={f.mode}
          setMode={f.setMode}
          lang={f.lang}
          setLang={f.setLang}
          focus={f.focus}
          setFocus={f.setFocus}
          files={f.files}
          setFiles={f.setFiles}
          addFiles={f.addFiles}
          applyStarter={f.applyStarter}
          running={f.running}
          uploading={f.uploading}
          onRun={f.run}
          showStarters={f.stage === 'idle' && !f.report}
        />
      )}

      {showProgress && (
        <ResearchProgress
          mode={f.mode}
          elapsedS={f.elapsedS}
          query={f.query}
          onCancel={f.cancel}
        />
      )}

      {showReport && (
        <ResearchReport
          report={f.report}
          citations={f.citations}
          meta={f.meta}
          mode={f.mode}
          downloadName={f.downloadName}
          elapsedS={f.elapsedS}
          onNew={f.reset}
        />
      )}

      {f.budgetModal}
      {f.dlpModal}
    </PageShell>
  )
}

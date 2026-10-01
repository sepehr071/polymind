import { Presentation, AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import PageShell from '../../components/layout/PageShell'
import PageHeader from '../../components/layout/PageHeader'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import usePresentationFlow from '@/hooks/usePresentationFlow'
import BriefStep from './components/BriefStep'
import OutlineEditor from './components/OutlineEditor'
import RenderProgress from './components/RenderProgress'
import DeckPreview from './components/DeckPreview'

/**
 * PresentationsPage — the 4-stage AI presentation generator.
 *
 *   brief      -> BriefStep: topic + options + sources, kicks the outline SSE
 *   outlining  -> RenderProgress: outline SSE in flight
 *   outline    -> OutlineEditor: edit slides before render
 *   rendering  -> RenderProgress: imaging + pptx SSE in flight
 *   ready      -> DeckPreview: reveal.js RTL preview + .pptx download
 *
 * All stage state + the SSE plumbing live in `usePresentationFlow`; this page is
 * a thin stage router. The 402 budget modal renders unconditionally (the hook
 * owns its open/close), and a non-budget `error` surfaces as a quiet inline row.
 */
export default function PresentationsPage() {
  const { t } = useTranslation('presentations')
  const f = usePresentationFlow()

  return (
    <PageShell width="standard">
      <PageHeader
        icon={Presentation}
        title={t('title')}
        subtitle={t('subtitle')}
        actions={<PrivacyBadge mode="cloud" />}
      />
      <PrivacyBanner mode="cloud" />

      {f.error && (
        <div
          className="flex items-center gap-2 rounded-xl border border-error/30 bg-error/5 px-4 py-3 text-sm text-error"
          role="alert"
          dir="auto"
        >
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="min-w-0 flex-1">
            {f.error === 'connection_lost' ? t('errors.connectionLost') : String(f.error)}
          </span>
        </div>
      )}

      {f.stage === f.STAGE.BRIEF && <BriefStep onStart={f.start} />}

      {f.stage === f.STAGE.OUTLINING && (
        <RenderProgress
          progress={f.progress}
          label={t(`phase.${f.progress?.phase || 'researching'}`, {
            defaultValue: t('phase.outlining'),
          })}
          warnings={f.warnings}
        />
      )}

      {f.stage === f.STAGE.OUTLINE && f.outline && (
        <OutlineEditor
          outline={f.outline}
          onChange={f.setOutline}
          onRender={f.render}
          onBack={f.reset}
        />
      )}

      {f.stage === f.STAGE.RENDERING && (
        <RenderProgress progress={f.progress} label={t('phase.rendering')} warnings={f.warnings} />
      )}

      {f.stage === f.STAGE.READY && (
        <DeckPreview outline={f.outline} file={f.file} onReset={f.reset} />
      )}

      {f.budgetModal}
    </PageShell>
  )
}

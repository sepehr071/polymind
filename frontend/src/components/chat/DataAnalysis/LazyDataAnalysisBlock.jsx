import { Suspense } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import lazyWithRetry from '../../../utils/lazyWithRetry'

// Lazy boundary for the Data Analyzer render kit. DataAnalysisBlock pulls in
// ECharts (charts/EChart + echartsCore, ~560KB) AND @tanstack/react-table —
// both heavy and used ONLY by intent='data' turns. Splitting them here keeps
// them OUT of the always-loaded ChatPage chunk (mirrors the CodeCanvas lazy
// split); ECharts/react-table load on demand the first time a data-analyzer
// message renders. Use lazyWithRetry (NOT React.lazy) so chunk-load retry
// applies on a stale-deploy 404.
const DataAnalysisBlock = lazyWithRetry(() => import('./DataAnalysisBlock'))

/**
 * Drop-in for DataAnalysisBlock that owns its own Suspense boundary, so call
 * sites (ChatWindow streaming turn, QuietMessage persisted turn, SharedChatView)
 * stay a one-line import swap. The fallback is a lightweight skeleton — no
 * ECharts — so it ships in the chat chunk and shows instantly while the heavy
 * chunk streams in. Props are forwarded verbatim: { steps, artifacts, streaming }.
 */
export default function LazyDataAnalysisBlock(props) {
  const { t } = useTranslation('chat')
  return (
    <Suspense
      fallback={
        <div
          className="mt-3 flex items-center gap-2 rounded-2xl border border-border bg-background px-3 py-3 text-sm text-foreground-tertiary shadow-[0_1px_2px_rgba(15,23,42,0.05)]"
          role="status"
        >
          <Loader2 className="h-4 w-4 animate-spin text-accent" aria-hidden="true" />
          <span>{t('dataAnalyzer.analyzing')}</span>
        </div>
      }
    >
      <DataAnalysisBlock {...props} />
    </Suspense>
  )
}

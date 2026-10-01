import { Component, memo, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Highlight, themes } from 'prism-react-renderer'
import {
  ChevronDown,
  Terminal,
  CircleAlert,
  BarChart3,
  Table as TableIcon,
  Loader2,
  Download,
  TrendingUp,
  Lightbulb,
  FileSpreadsheet,
  FileJson,
  File as FileIcon,
} from 'lucide-react'
import { cn } from '../../../utils/cn'
import { useTheme } from '../../../context/ThemeContext'
import { useEchartTheme } from '../../charts/useEchartTheme'
import { fmtNumber } from '../../../utils/persianLocale'
import { IconTile } from '../../ui/icon-tile'
import { StatTile } from '../../ui/StatTile'
import { Card } from '../../ui/card'
import { API_BASE_URL } from '@/services/apiBase'
import DataChart from './DataChart'
import DataTable from './DataTable'

/**
 * Data Analyzer render block — the in-chat surface for the agentic Python
 * tool-loop. Two parts, attached BENEATH the assistant's prose answer:
 *
 *   1. A collapsible "Analysis steps (N)" timeline. Each step = the run_python
 *      code (Prism, LTR) + its stdout / error. While the loop is streaming the
 *      timeline auto-expands with a "Running step N…" indicator (CSS keyframes,
 *      NOT framer — framer repeat:Infinity can paint dead-static here); once the
 *      final answer settles it collapses by default so the answer stays primary.
 *
 *   2. The artifacts: chart → <DataChart>, table → <DataTable>, in emit order.
 *
 * Live vs persisted are the SAME shape:
 *   { steps:[{ step, code, stdout, error }], artifacts:[<artifact>] }
 * Live: accumulated onto the in-flight streaming message by useChatStream and
 * passed via `streaming`. Persisted: read from message.metadata.data_artifacts.
 *
 * @param {Array<{ step:number, code:string, stdout?:string, error?:string|null }>} steps
 * @param {Array<object>} artifacts  chart/table artifact specs
 * @param {boolean} [streaming]      true while the tool-loop is still running
 */

/* Reuse the codebase blink/pulse idiom. The 3-dot "running" wave uses the
   shared `.animate-pulse-dot` keyframe from index.css (same as StreamingTurn),
   so nothing new is injected here. */

function StepCode({ code, isDark }) {
  const prismTheme = isDark ? themes.oneDark : themes.oneLight
  return (
    <Highlight theme={prismTheme} code={String(code ?? '').replace(/\n$/, '')} language="python">
      {({ className, style, tokens, getLineProps, getTokenProps }) => (
        <pre
          dir="ltr"
          className={cn(className, 'rounded-md text-start')}
          style={{
            ...style,
            margin: 0,
            padding: '0.75rem 0.875rem',
            overflow: 'auto',
            maxHeight: '320px',
            fontSize: '0.8125rem',
            lineHeight: '1.5',
            textAlign: 'left',
          }}
        >
          {tokens.map((line, i) => (
            <div key={i} {...getLineProps({ line })}>
              <span
                aria-hidden="true"
                style={{
                  display: 'inline-block',
                  width: '2ch',
                  marginRight: '1ch',
                  opacity: 0.35,
                  userSelect: 'none',
                  textAlign: 'right',
                }}
              >
                {i + 1}
              </span>
              {line.map((token, key) => (
                <span key={key} {...getTokenProps({ token })} />
              ))}
            </div>
          ))}
        </pre>
      )}
    </Highlight>
  )
}

const StepRow = memo(function StepRow({ step, index, total, isDark, streaming }) {
  const { t } = useTranslation('chat')
  const hasError = !!step?.error
  // The last step is "live" while the loop streams (its result may not be in yet).
  const isLive = streaming && index === total - 1 && !step?.done && !hasError

  return (
    <li className="relative ps-6">
      {/* Timeline rail + node */}
      <span
        aria-hidden="true"
        className="absolute start-0 top-1 flex h-4 w-4 items-center justify-center rounded-full border border-border bg-background-secondary text-[10px] font-semibold text-foreground-secondary"
      >
        {fmtNumber(step?.step ?? index + 1)}
      </span>
      {index < total - 1 && (
        <span
          aria-hidden="true"
          className="absolute start-[7px] top-5 bottom-[-12px] w-px bg-border"
        />
      )}

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 text-xs text-foreground-tertiary">
          <Terminal className="h-3 w-3" aria-hidden="true" />
          <span>{t('dataAnalyzer.runPython')}</span>
          {isLive && (
            <span className="ms-1 inline-flex items-center gap-1 text-accent">
              <span className="flex gap-0.5">
                {[0, 0.15, 0.3].map((d, i) => (
                  <span
                    key={i}
                    className="h-1 w-1 rounded-full bg-accent/70 animate-pulse-dot"
                    style={{ animationDelay: `${d}s` }}
                  />
                ))}
              </span>
              <span>{t('dataAnalyzer.runningStep', { n: fmtNumber(step?.step ?? index + 1) })}</span>
            </span>
          )}
        </div>

        <StepCode code={step?.code} isDark={isDark} />

        {step?.stdout != null && String(step.stdout).trim() !== '' && (
          <div>
            <div className="mb-0.5 text-[11px] font-medium uppercase tracking-wide text-foreground-tertiary">
              {t('dataAnalyzer.output')}
            </div>
            <pre
              dir="ltr"
              className="max-h-40 overflow-auto rounded-md border border-border bg-background-tertiary/60 px-3 py-2 text-start text-[12px] leading-relaxed text-foreground/85"
              style={{ whiteSpace: 'pre-wrap', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' }}
            >
              {String(step.stdout)}
            </pre>
          </div>
        )}

        {hasError && (
          <div>
            <div className="mb-0.5 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-error">
              <CircleAlert className="h-3 w-3" aria-hidden="true" />
              {t('dataAnalyzer.error')}
            </div>
            <pre
              dir="ltr"
              className="max-h-40 overflow-auto rounded-md border border-error/30 bg-error/5 px-3 py-2 text-start text-[12px] leading-relaxed text-error"
              style={{ whiteSpace: 'pre-wrap', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' }}
            >
              {String(step.error)}
            </pre>
          </div>
        )}
      </div>
    </li>
  )
})

/* ── Chart artifact: chart + a top-end PNG download button ──────────────────
   The chart instance is plumbed up via DataChart → EChart `instanceRef`. We hold
   the live instance in a ref and, on click, `getDataURL` it to a PNG (2× pixel
   ratio, opaque themed background so transparent canvases don't export black)
   then anchor-download it — mirroring the exportCsv.js download idiom. */
function ChartArtifact({ artifact }) {
  const { t } = useTranslation('chat')
  const echartTheme = useEchartTheme()
  const chartInstanceRef = useRef(null)

  const handleDownloadPng = () => {
    const chart = chartInstanceRef.current
    if (!chart) return
    const url = chart.getDataURL({
      type: 'png',
      pixelRatio: 2,
      backgroundColor: echartTheme.tooltipBg, // resolved --background-elevated literal
    })
    const safeTitle = String(artifact.title || 'chart')
      .trim()
      .replace(/[^\p{L}\p{N}_-]+/gu, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 80)
    const a = document.createElement('a')
    a.href = url
    a.download = `${safeTitle || 'chart'}.png`
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  return (
    <Card component="figure" className="relative my-1 p-3">
      <button
        type="button"
        onClick={handleDownloadPng}
        aria-label={t('dataAnalyzer.downloadChart')}
        title={t('dataAnalyzer.downloadChart')}
        className="absolute end-2 top-2 z-10 inline-flex h-7 w-7 items-center justify-center rounded-md text-foreground-tertiary transition-colors hover:bg-background-tertiary hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      <DataChart
        kind={artifact.kind}
        encoding={artifact.encoding}
        data={artifact.data}
        title={artifact.title}
        instanceRef={(chart) => { chartInstanceRef.current = chart }}
      />
    </Card>
  )
}

/* ── Metric artifact → StatTile KPI card ────────────────────────────────────
   Numbers format through fmtNumber + an optional unit suffix; strings render
   verbatim. delta/direction/spark map straight onto StatTile's contract. */
function MetricArtifact({ artifact }) {
  const value =
    typeof artifact.value === 'number'
      ? `${fmtNumber(artifact.value)}${artifact.unit ? ` ${artifact.unit}` : ''}`
      : String(artifact.value ?? '')
  const spark = Array.isArray(artifact.spark) && artifact.spark.length > 0 ? artifact.spark : undefined
  return (
    <StatTile
      icon={TrendingUp}
      label={artifact.label}
      value={value}
      delta={artifact.delta != null ? Number(artifact.delta) : null}
      deltaDirection={artifact.direction || 'neutral'}
      spark={spark}
    />
  )
}

/* ── Insight artifact → tinted callout ──────────────────────────────────────
   level ∈ info|success|warning tints the border / IconTile tone using existing
   semantic tokens (no new colors). */
const INSIGHT_LEVELS = {
  info: { tone: 'neutral', border: 'border-border', bg: 'bg-background-secondary/40', text: 'text-foreground/90' },
  success: { tone: 'emerald', border: 'border-success/30', bg: 'bg-success/5', text: 'text-foreground/90' },
  warning: { tone: 'amber', border: 'border-warning/30', bg: 'bg-warning/5', text: 'text-foreground/90' },
}
function InsightArtifact({ artifact }) {
  const { t } = useTranslation('chat')
  const cfg = INSIGHT_LEVELS[artifact.level] || INSIGHT_LEVELS.info
  return (
    <div
      role="note"
      aria-label={t('dataAnalyzer.insight')}
      className={cn('my-1 flex items-start gap-2.5 rounded-lg border p-3', cfg.border, cfg.bg)}
    >
      <IconTile icon={Lightbulb} tone={cfg.tone} size="md" />
      <p className={cn('text-sm leading-relaxed', cfg.text)} dir="auto">
        {artifact.text}
      </p>
    </div>
  )
}

/* ── File artifact: a downloadable file the analysis produced (cleaned export,
   generated workbook, etc.) ─────────────────────────────────────────────────
   The backend ships { name, ext, size, mime, upload_id, url }; `url` is the
   root-relative '/api/uploads/<id>'. We resolve it against API_BASE_URL so a
   split-domain deploy (FE origin ≠ API origin) hits the API origin instead of
   404ing on the FE; same-origin is unchanged. The cross-origin download relies
   on the server's Content-Disposition: attachment header, so a plain
   <a href download> still works — no fetch/Bearer. ext picks the glyph; size
   renders human-readable with localized digits. */
function humanFileSize(bytes) {
  const n = Number(bytes)
  if (!Number.isFinite(n) || n <= 0) return null
  if (n < 1024 * 1024) return `${fmtNumber(Math.round((n / 1024) * 10) / 10)} KB`
  return `${fmtNumber(Math.round((n / (1024 * 1024)) * 10) / 10)} MB`
}

function fileIconForExt(ext) {
  const e = String(ext || '').toLowerCase()
  if (e === 'xlsx' || e === 'xls' || e === 'csv' || e === 'xlsm') return FileSpreadsheet
  if (e === 'json' || e === 'jsonl') return FileJson
  return FileIcon
}

function FileArtifact({ artifact }) {
  const { t } = useTranslation('chat')
  if (!artifact.url) return null

  // artifact.url is root-relative ('/api/uploads/<id>'); on a split-domain deploy
  // (VITE_API_BASE_URL = api.<host>/api) it must resolve to the API origin, not the
  // FE origin. Same-origin (API_BASE_URL = '/api') → apiOrigin '' → unchanged.
  const apiOrigin = API_BASE_URL.replace(/\/api$/, '')
  const href = /^https?:\/\//i.test(artifact.url) ? artifact.url : `${apiOrigin}${artifact.url}`

  const Icon = fileIconForExt(artifact.ext)
  const size = humanFileSize(artifact.size)

  return (
    <Card className="my-1 flex items-center gap-3 p-3">
      <IconTile icon={Icon} tone="emerald" size="md" />
      <div className="min-w-0 flex-1">
        {/* dir=auto: filenames are often Persian — hard ltr renders them with
            the extension visually glued to the wrong side. */}
        <p className="truncate text-sm font-medium text-foreground" dir="auto">
          {artifact.name}
        </p>
        {size && (
          <p className="mt-0.5 text-xs text-foreground-tertiary">{size}</p>
        )}
      </div>
      <a
        href={href}
        download
        className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-background-secondary px-2.5 py-1.5 text-xs font-medium text-foreground-secondary transition-colors hover:bg-background-tertiary hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        {t('dataAnalyzer.downloadFile')}
      </a>
    </Card>
  )
}

function ArtifactView({ artifact }) {
  if (!artifact || typeof artifact !== 'object') return null

  if (artifact.type === 'chart') {
    return <ChartArtifact artifact={artifact} />
  }

  if (artifact.type === 'table') {
    return (
      <DataTable
        columns={artifact.columns}
        rows={artifact.rows}
        total_rows={artifact.total_rows}
        name={artifact.name}
      />
    )
  }

  if (artifact.type === 'metric') {
    return <MetricArtifact artifact={artifact} />
  }

  if (artifact.type === 'insight') {
    return <InsightArtifact artifact={artifact} />
  }

  if (artifact.type === 'file') {
    return <FileArtifact artifact={artifact} />
  }

  return null
}

/* ── Per-artifact error boundary ────────────────────────────────────────────
   A single malformed artifact (e.g. a table whose columns react-table rejects)
   must NEVER throw past here — otherwise the page-level boundary blankets the
   whole Data Analyzer (rail + history included), which reads as "my history is
   gone". Each artifact renders inside its own boundary, degrading to a quiet
   one-line notice while everything else stays intact. */
class ArtifactBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { failed: false }
  }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error, info) {
    console.error('[DataArtifact]', error, info?.componentStack)
  }

  render() {
    if (this.state.failed) {
      return (
        <Card className="my-1 px-3 py-2 text-xs text-foreground-tertiary">
          {this.props.label}
        </Card>
      )
    }
    return this.props.children
  }
}

function DataAnalysisBlockBase({ steps, artifacts, streaming = false }) {
  const { t } = useTranslation('chat')
  const { isDark } = useTheme()

  const stepList = Array.isArray(steps) ? steps : []
  const artifactList = Array.isArray(artifacts) ? artifacts : []

  // Collapsed by default in BOTH states. The collapsed header already carries a
  // live "Analyzing… step N" status while streaming, so the work stays visible
  // as a thin bar without the tall, jumpy code timeline shoving the answer
  // around (expanding to watch the code run is opt-in). Identical live/persisted
  // height also means no jump on the live→persisted swap. We track the user's
  // manual override separately so an expand mid-stream sticks.
  const [userToggled, setUserToggled] = useState(null) // null | boolean
  const expanded = userToggled != null ? userToggled : false

  // When a stream finishes, reset the manual override so the block re-collapses
  // (unless the user explicitly expanded it during the run, which we keep).
  useEffect(() => {
    if (!streaming) setUserToggled((prev) => (prev === true ? true : null))
  }, [streaming])

  const counts = useMemo(() => {
    let charts = 0
    let tables = 0
    for (const a of artifactList) {
      if (a?.type === 'chart') charts += 1
      else if (a?.type === 'table') tables += 1
    }
    return { charts, tables }
  }, [artifactList])

  // Coalesce CONSECUTIVE metric artifacts into one responsive grid of KPI cards
  // (so a row of metrics reads as a dashboard strip, not a stack), while every
  // other artifact type renders individually in emit order. Build the grouped
  // render list once per artifact change.
  const renderGroups = useMemo(() => {
    const groups = []
    let metricRun = null
    for (let i = 0; i < artifactList.length; i += 1) {
      const a = artifactList[i]
      if (a?.type === 'metric') {
        if (!metricRun) {
          metricRun = { kind: 'metrics', items: [], key: `m-${i}` }
          groups.push(metricRun)
        }
        metricRun.items.push({ artifact: a, key: i })
      } else {
        metricRun = null
        groups.push({ kind: 'single', artifact: a, key: i })
      }
    }
    return groups
  }, [artifactList])

  // Nothing to show — the assistant answered in prose with no tool activity.
  if (stepList.length === 0 && artifactList.length === 0) return null

  return (
    <div className="mt-3 space-y-3">
      {/* ── Steps timeline (collapsible) ── */}
      {stepList.length > 0 && (
        <Card className="overflow-hidden">
          <button
            type="button"
            onClick={() => setUserToggled(!expanded)}
            aria-expanded={expanded}
            className="flex w-full items-center gap-2 px-3 py-2 text-start text-sm font-medium text-foreground-secondary transition-colors hover:bg-background-tertiary/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          >
            {streaming ? (
              <Loader2 className="h-4 w-4 shrink-0 animate-spin text-accent" aria-hidden="true" />
            ) : (
              <Terminal className="h-4 w-4 shrink-0 text-foreground-tertiary" aria-hidden="true" />
            )}
            <span className="flex-1">
              {streaming
                ? t('dataAnalyzer.analyzingStep', { n: fmtNumber(stepList.length) })
                : t('dataAnalyzer.steps', { count: stepList.length })}
            </span>
            <ChevronDown
              className={cn(
                'h-4 w-4 shrink-0 text-foreground-tertiary transition-transform duration-200',
                expanded && 'rotate-180',
              )}
              aria-hidden="true"
            />
          </button>

          {expanded && (
            <div className="border-t border-border px-3 py-3">
              <ol className="space-y-3">
                {stepList.map((step, i) => (
                  <StepRow
                    key={step?.step ?? i}
                    step={step}
                    index={i}
                    total={stepList.length}
                    isDark={isDark}
                    streaming={streaming}
                  />
                ))}
              </ol>
            </div>
          )}
        </Card>
      )}

      {/* ── Artifacts ── */}
      {/* Charts/tables/KPI grids fill the host column. On the dedicated Data
          Analyzer page that column is widened (maxColumnWidth=1024) so artifacts
          breathe; inside the narrower chat reading lane they bind to it. The cap
          keeps them sane on very wide future columns. ECharts auto-resizes via
          EChart's ResizeObserver when the container width changes. */}
      {artifactList.length > 0 && (
        <div className="mx-auto w-full max-w-[1280px] space-y-3">
          {(counts.charts > 0 || counts.tables > 0) && (
            <div className="flex items-center gap-3 text-xs text-foreground-tertiary">
              {counts.charts > 0 && (
                <span className="inline-flex items-center gap-1">
                  <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />
                  {t('dataAnalyzer.charts', { count: counts.charts })}
                </span>
              )}
              {counts.tables > 0 && (
                <span className="inline-flex items-center gap-1">
                  <TableIcon className="h-3.5 w-3.5" aria-hidden="true" />
                  {t('dataAnalyzer.tables', { count: counts.tables })}
                </span>
              )}
            </div>
          )}
          {renderGroups.map((group) =>
            group.kind === 'metrics' ? (
              <ArtifactBoundary key={group.key} label={t('dataAnalyzer.renderFailed')}>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                  {group.items.map((m) => (
                    <ArtifactView key={m.key} artifact={m.artifact} />
                  ))}
                </div>
              </ArtifactBoundary>
            ) : (
              <ArtifactBoundary key={group.key} label={t('dataAnalyzer.renderFailed')}>
                <ArtifactView artifact={group.artifact} />
              </ArtifactBoundary>
            ),
          )}
        </div>
      )}
    </div>
  )
}

export const DataAnalysisBlock = memo(DataAnalysisBlockBase)
export default DataAnalysisBlock

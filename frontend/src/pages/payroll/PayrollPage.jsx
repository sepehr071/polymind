import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import {
  Receipt,
  UploadCloud,
  FileSpreadsheet,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Sparkles,
  Users,
  RotateCcw,
} from 'lucide-react'
import PageShell from '../../components/layout/PageShell'
import PageHeader from '../../components/layout/PageHeader'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Progress } from '../../components/ui/progress'
import { IconTile } from '../../components/ui/icon-tile'
import FileDownloadCard from '../../components/ui/FileDownloadCard'
import {
  uploadPayrollFile,
  previewPayroll,
  streamPayrollGenerate,
} from '../../services/payrollService'
import { fmtNumber } from '../../utils/persianLocale'
import { cn } from '@/lib/utils'

const ACCEPT = '.xlsx,.xls'

const GEN_PHASES = ['parsing', 'rendering', 'zipping']

/**
 * PayrollPage — accountant workflow:
 *   1. Upload a monthly all-employees payroll workbook (xlsx/xls).
 *   2. Preview the parsed employees (name, code, net, earnings, deductions).
 *   3. Generate → SSE progress → download a ZIP of one Persian payslip
 *      (فیش حقوقی) PDF per employee.
 *
 * Layout: an in-flow PageHeader (amber/studio tone auto-derived from the
 * /payroll nav zone) over a single capped form lane (PageShell width="form",
 * ~768px). Each async surface (upload, preview, generate) carries explicit
 * loading / error / empty states — never just the happy path.
 */
export default function PayrollPage() {
  const { t } = useTranslation('payroll')
  const location = useLocation()

  // ── Upload state ──
  const [fileName, setFileName] = useState('')
  const [uploadId, setUploadId] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(false)

  // ── Optional overrides ──
  const [employer, setEmployer] = useState('')
  const [month, setMonth] = useState('')

  // ── Preview state ──
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState(false)

  // ── Generate state ──
  const [generating, setGenerating] = useState(false)
  const [genStatus, setGenStatus] = useState(null) // { phase, done?, total? }
  const [genError, setGenError] = useState(null) // string | null
  const [resultFile, setResultFile] = useState(null) // { url, name, ext, size }

  const fileInputRef = useRef(null)
  const genStreamRef = useRef(null)
  // Guard setState after a superseded async op (unmount / re-trigger).
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  // Cancel an in-flight generate stream on route change / unmount.
  useEffect(() => {
    return () => {
      if (genStreamRef.current) {
        try {
          genStreamRef.current.abort()
        } catch {
          /* ignore */
        }
        genStreamRef.current = null
      }
    }
  }, [location.pathname])

  // Run a preview against the current upload + overrides. Extracted so the
  // file-pick handler and the "Re-read with overrides" affordance share it.
  const runPreview = useCallback(
    async (id, opts = {}) => {
      if (!id) return
      setPreviewLoading(true)
      setPreviewError(false)
      try {
        const data = await previewPayroll({
          upload_id: id,
          employer: opts.employer ?? employer,
          month: opts.month ?? month,
        })
        if (!aliveRef.current) return
        setPreview(data)
      } catch {
        if (!aliveRef.current) return
        setPreviewError(true)
        setPreview(null)
      } finally {
        if (aliveRef.current) setPreviewLoading(false)
      }
    },
    [employer, month],
  )

  const handleFilePick = useCallback(
    async (e) => {
      const file = e.target.files?.[0]
      // Allow re-picking the same file later (onChange won't fire otherwise).
      if (fileInputRef.current) fileInputRef.current.value = ''
      if (!file) return

      // Reset any prior run — a new file means a clean slate.
      setFileName(file.name)
      setUploadError(false)
      setPreview(null)
      setPreviewError(false)
      setResultFile(null)
      setGenError(null)
      setGenStatus(null)
      setUploadId(null)
      setUploading(true)

      let upload
      try {
        upload = await uploadPayrollFile(file)
      } catch {
        if (!aliveRef.current) return
        setUploadError(true)
        setUploading(false)
        return
      }
      if (!aliveRef.current) return
      setUploading(false)

      const id = upload?.id
      if (!id) {
        setUploadError(true)
        return
      }
      setUploadId(id)
      // Auto-preview right after a successful upload.
      runPreview(id)
    },
    [runPreview],
  )

  const handleGenerate = useCallback(() => {
    if (!uploadId || generating) return
    // Tear down any prior stream before starting a fresh one.
    if (genStreamRef.current) {
      try {
        genStreamRef.current.abort()
      } catch {
        /* ignore */
      }
      genStreamRef.current = null
    }
    setGenerating(true)
    setGenError(null)
    setResultFile(null)
    setGenStatus({ phase: 'parsing' })

    genStreamRef.current = streamPayrollGenerate(
      { upload_id: uploadId, employer, month },
      {
        onStatus: (d) => {
          if (!aliveRef.current) return
          setGenStatus(d || {})
        },
        onFile: (d) => {
          if (!aliveRef.current) return
          setResultFile(d)
        },
        onError: (d) => {
          if (!aliveRef.current) return
          setGenError(d?.error || t('generate.error'))
          setGenerating(false)
          genStreamRef.current = null
        },
        onDone: () => {
          if (!aliveRef.current) return
          setGenerating(false)
          genStreamRef.current = null
        },
      },
    )
  }, [uploadId, generating, employer, month, t])

  // Derived progress (0–100). When total is unknown we show an indeterminate
  // sweep via the label only; the bar stays at a low determinate value so it
  // never reads as "complete".
  const progressPct = useMemo(() => {
    const done = Number(genStatus?.done)
    const total = Number(genStatus?.total)
    if (Number.isFinite(done) && Number.isFinite(total) && total > 0) {
      return Math.min(100, Math.round((done / total) * 100))
    }
    return null
  }, [genStatus])

  const phase = genStatus?.phase && GEN_PHASES.includes(genStatus.phase) ? genStatus.phase : 'parsing'

  const records = Array.isArray(preview?.records) ? preview.records : []
  const warnings = Array.isArray(preview?.warnings) ? preview.warnings : []
  const columnsOk = preview ? preview.columns_ok !== false : true

  const hasUpload = !!uploadId
  const canGenerate = hasUpload && columnsOk && !uploading && !previewLoading

  return (
    <PageShell width="form">
      {/* ── Header (in-flow, non-glass) ── */}
      <PageHeader
        icon={Receipt}
        title={t('title')}
        subtitle={t('subtitle')}
        actions={<PrivacyBadge mode="cloud" />}
      />
      <PrivacyBanner mode="cloud" />

      {/* ===== 1. Upload ===== */}
      <section aria-labelledby="payroll-upload-heading" className="space-y-3">
        <SectionTitle id="payroll-upload-heading" icon={FileSpreadsheet} tone="amber">
          {t('upload.title')}
        </SectionTitle>

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT}
          onChange={handleFilePick}
          className="sr-only"
          aria-hidden="true"
          tabIndex={-1}
        />

        {/* Dropzone-style picker. Click anywhere to open the file dialog. */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className={cn(
            'group flex w-full items-center gap-4 rounded-2xl border border-dashed border-border bg-background-secondary p-5 text-start transition-colors',
            'hover:border-accent/50 hover:bg-accent/5',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
            'disabled:cursor-wait disabled:opacity-70',
          )}
          aria-busy={uploading}
        >
          <IconTile
            icon={uploading ? Loader2 : hasUpload ? CheckCircle2 : UploadCloud}
            tone={hasUpload ? 'emerald' : 'amber'}
            size="lg"
            iconClassName={uploading ? 'animate-spin' : undefined}
          />
          <div className="min-w-0 flex-1">
            {fileName ? (
              <p className="truncate text-sm font-medium text-foreground" dir="auto">
                {fileName}
              </p>
            ) : (
              <p className="text-sm font-medium text-foreground">{t('upload.choose')}</p>
            )}
            <p className="mt-0.5 text-xs text-foreground-tertiary">
              {uploading
                ? t('upload.uploading')
                : hasUpload
                  ? t('upload.uploaded')
                  : t('upload.dropHint')}
            </p>
          </div>
          {hasUpload && !uploading && (
            <span className="shrink-0 text-xs font-medium text-foreground-secondary transition-colors group-hover:text-foreground">
              {t('upload.change')}
            </span>
          )}
        </button>

        {uploadError && (
          <InlineError>{t('upload.error')}</InlineError>
        )}

        {/* Optional overrides — only meaningful once a file is attached. */}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            id="payroll-employer"
            label={t('upload.employerLabel')}
            hint={t('upload.employerHint')}
          >
            <Input
              id="payroll-employer"
              value={employer}
              onChange={(e) => setEmployer(e.target.value)}
              onBlur={() => hasUpload && runPreview(uploadId)}
              placeholder={t('upload.employerPlaceholder')}
              dir="auto"
              disabled={uploading}
            />
          </Field>
          <Field
            id="payroll-month"
            label={t('upload.monthLabel')}
            hint={t('upload.monthHint')}
          >
            <Input
              id="payroll-month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              onBlur={() => hasUpload && runPreview(uploadId)}
              placeholder={t('upload.monthPlaceholder')}
              dir="auto"
              disabled={uploading}
            />
          </Field>
        </div>
      </section>

      {/* ===== 2. Preview ===== */}
      {(previewLoading || previewError || preview) && (
        <section aria-labelledby="payroll-preview-heading" className="space-y-3">
          <SectionTitle id="payroll-preview-heading" icon={Users} tone="amber">
            {t('preview.title')}
          </SectionTitle>

          {previewLoading ? (
            <Card className="flex items-center justify-center gap-2 py-12 text-sm text-foreground-tertiary">
              <Loader2 className="h-4 w-4 animate-spin text-accent" aria-hidden="true" />
              {t('preview.analyzing')}
            </Card>
          ) : previewError ? (
            <InlineError>{t('preview.error')}</InlineError>
          ) : !columnsOk ? (
            <CalloutError
              title={t('preview.columnsError.title')}
              body={t('preview.columnsError.body')}
            />
          ) : (
            <PreviewBlock
              t={t}
              preview={preview}
              records={records}
              warnings={warnings}
            />
          )}
        </section>
      )}

      {/* ===== 3. Generate + progress ===== */}
      {hasUpload && columnsOk && !previewLoading && (
        <section aria-labelledby="payroll-generate-heading" className="space-y-3">
          <SectionTitle id="payroll-generate-heading" icon={Sparkles} tone="amber">
            {t('generate.button')}
          </SectionTitle>

          <Card className="p-5">
            <Button
              onClick={handleGenerate}
              disabled={!canGenerate || generating}
              className="w-full sm:w-auto"
              animated
            >
              {generating ? (
                <>
                  <Loader2 className="me-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  {t('generate.running')}
                </>
              ) : (
                <>
                  <Sparkles className="me-2 h-4 w-4" aria-hidden="true" />
                  {resultFile ? t('result.regenerate') : t('generate.button')}
                </>
              )}
            </Button>

            {/* Live progress */}
            {generating && (
              <div className="mt-4 space-y-2" aria-live="polite">
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span className="font-medium text-foreground-secondary">
                    {t(`generate.phase.${phase}`)}
                  </span>
                  <span className="tabular-nums text-foreground-tertiary" dir="ltr">
                    {progressPct != null && genStatus?.total
                      ? t('generate.progressOf', {
                          done: fmtNumber(genStatus.done ?? 0),
                          total: fmtNumber(genStatus.total),
                        })
                      : t('generate.preparing')}
                  </span>
                </div>
                <Progress
                  value={progressPct ?? indeterminateValue(phase)}
                  variant="default"
                  size="default"
                />
              </div>
            )}

            {/* Generation error (inline, never a toast) */}
            {genError && !generating && (
              <div className="mt-4">
                <InlineError onRetry={handleGenerate} retryLabel={t('generate.button')}>
                  {genError}
                </InlineError>
              </div>
            )}
          </Card>
        </section>
      )}

      {/* ===== 4. Result ===== */}
      {resultFile && !generating && (
        <section aria-labelledby="payroll-result-heading" className="space-y-3">
          <SectionTitle id="payroll-result-heading" icon={CheckCircle2} tone="emerald">
            {t('result.title')}
          </SectionTitle>
          <p className="text-sm text-foreground-secondary">{t('result.body')}</p>
          <FileDownloadCard
            artifact={resultFile}
            downloadLabel={t('download.label')}
            tone="emerald"
          />
        </section>
      )}
    </PageShell>
  )
}

// Indeterminate-but-determinate: while total is unknown, nudge the bar per phase
// so it visibly advances (parsing → rendering → zipping) without ever hitting
// 100% before the file event lands.
function indeterminateValue(phase) {
  switch (phase) {
    case 'parsing':
      return 15
    case 'rendering':
      return 55
    case 'zipping':
      return 90
    default:
      return 10
  }
}

/* ── Section heading: tinted IconTile + label ── */
function SectionTitle({ id, icon, tone = 'amber', children }) {
  return (
    <h2 id={id} className="flex items-center gap-2.5 text-base font-semibold text-foreground">
      <IconTile icon={icon} tone={tone} size="md" />
      {children}
    </h2>
  )
}

/* ── Labeled field with a hint line ── */
function Field({ id, label, hint, children }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-foreground-secondary">
        {label}
      </Label>
      {children}
      {hint && <p className="text-xs text-foreground-tertiary">{hint}</p>}
    </div>
  )
}

/* ── Quiet inline error row with an optional retry ── */
function InlineError({ children, onRetry, retryLabel }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-error/30 bg-error/5 px-4 py-3 text-sm text-error">
      <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="flex-1 min-w-0">{children}</span>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="gap-1.5" animated={false}>
          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
          {retryLabel}
        </Button>
      )}
    </div>
  )
}

/* ── Larger callout for a hard validation failure (missing columns) ── */
function CalloutError({ title, body }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-error/30 bg-error/5 p-5">
      <IconTile icon={AlertTriangle} tone="rose" size="md" />
      <div className="min-w-0">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="mt-1 text-sm text-foreground-secondary leading-relaxed">{body}</p>
      </div>
    </div>
  )
}

/* ── Preview block: detected meta, count, warnings, employee table ── */
function PreviewBlock({ t, preview, records, warnings }) {
  const count = Number(preview?.count) || records.length
  const detected = preview?.month || preview?.employer

  return (
    <div className="space-y-4">
      {/* Meta strip: detected month/employer + count */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {detected ? (
          <p className="text-sm text-foreground-secondary" dir="auto">
            {t('preview.detected', {
              month: preview?.month || '—',
              employer: preview?.employer || '—',
            })}
          </p>
        ) : (
          <span />
        )}
        <span className="inline-flex items-center gap-1.5 rounded-full bg-accent/10 px-3 py-1 text-[11px] font-semibold text-accent">
          <Users className="h-3.5 w-3.5" aria-hidden="true" />
          {t('preview.count', { count })}
        </span>
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="rounded-xl border border-warning/30 bg-warning/5 p-4">
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-warning">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
            {t('preview.warningsTitle')}
          </p>
          <ul className="list-disc space-y-0.5 ps-5 text-sm text-foreground-secondary">
            {warnings.map((w, i) => (
              <li key={i} dir="auto">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Employee table */}
      {records.length === 0 ? (
        <Card className="py-10 text-center text-sm text-foreground-tertiary">
          {t('preview.empty')}
        </Card>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-border">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-border bg-background-secondary text-xs font-bold text-foreground-secondary">
                  <th className="px-4 py-2.5 text-start font-bold">
                    {t('preview.columns.name')}
                  </th>
                  <th className="px-4 py-2.5 text-start font-bold">
                    {t('preview.columns.code')}
                  </th>
                  <th className="px-4 py-2.5 text-end font-bold">
                    {t('preview.columns.earnings')}
                  </th>
                  <th className="px-4 py-2.5 text-end font-bold">
                    {t('preview.columns.deductions')}
                  </th>
                  <th className="px-4 py-2.5 text-end font-bold">
                    {t('preview.columns.net')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {records.map((r, i) => (
                  <tr
                    key={r.code || i}
                    className="border-b border-border/60 last:border-0 transition-colors hover:bg-background-secondary/40"
                  >
                    <td className="px-4 py-2.5 text-foreground" dir="auto">
                      {r.name || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-foreground-secondary" dir="ltr">
                      {r.code || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary" dir="ltr">
                      {fmtNumber(r.earnings_total)}
                    </td>
                    <td className="px-4 py-2.5 text-end tabular-nums text-foreground-secondary" dir="ltr">
                      {fmtNumber(r.deductions_total)}
                    </td>
                    <td className="px-4 py-2.5 text-end tabular-nums font-medium text-foreground" dir="ltr">
                      {fmtNumber(r.net)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

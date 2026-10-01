import { useRef } from 'react'
import { AlertTriangle, Copy, Download, FileSearch, Loader2, Upload, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Card } from '@/components/ui/card'
import useContractReviewFlow from '@/hooks/useContractReviewFlow'
import { cn } from '@/lib/utils'

function formatBytes(n) {
  if (n == null || Number.isNaN(n)) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function uiDisclaimer(r, lang) {
  const base = String(lang || 'fa').split('-')[0]
  if (!r?.disclaimer) return ''
  if (base === 'en') return r.disclaimer.en || r.disclaimer.fa || ''
  return r.disclaimer.fa || r.disclaimer.en || ''
}

const LEVEL_CLASS = {
  low: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  medium: 'bg-amber-500/15 text-amber-800 dark:text-amber-300',
  high: 'bg-orange-500/15 text-orange-800 dark:text-orange-300',
  critical: 'bg-red-500/15 text-red-700 dark:text-red-300',
}

function toMarkdown(r, lang) {
  if (!r) return ''
  const disc = uiDisclaimer(r, lang)
  const lines = [
    `# ${r.summary?.slice(0, 80) || 'Contract review'}`,
    '',
    ...(disc ? [`**${disc}**`, ''] : []),
    '## Summary',
    r.summary || '',
    '',
    '## Risk matrix',
    ...(r.risk_matrix || []).map(
      (row) => `- **${row.area}** (${row.risk_level}): ${row.finding} → ${row.recommendation}`,
    ),
    '',
    '## Key clauses',
    ...(r.key_clauses || []).map((c) => `- ${c}`),
    '',
    '## Open questions',
    ...(r.open_questions || []).map((c) => `- ${c}`),
    '',
    '## Red flags',
    ...(r.red_flags || []).map((c) => `- ${c}`),
  ]
  return lines.join('\n')
}

export default function ContractsPage() {
  const { t, i18n } = useTranslation('contracts')
  const f = useContractReviewFlow()
  const inputRef = useRef(null)
  const replaceIdRef = useRef(null)
  const r = f.result
  const uiLang = (i18n.language || 'fa').split('-')[0]
  const resultDisclaimer = uiDisclaimer(r, uiLang)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(toMarkdown(r, uiLang))
      toast.success(t('copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }
  const download = () => {
    const blob = new Blob([toMarkdown(r, uiLang)], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'contract-review.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <PageShell width="standard">
      <PageHeader
        icon={FileSearch}
        title={t('title')}
        subtitle={t('subtitle')}
        actions={<PrivacyBadge mode="cloud" />}
      />
      <PrivacyBanner mode="cloud" />
      <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm" role="note">
        <p>{t('disclaimer')}</p>
      </div>
      {f.error && (
        <div className="flex gap-2 rounded-xl border border-error/30 bg-error/5 px-4 py-3 text-sm text-error">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{String(f.error)}</span>
        </div>
      )}
      <Card className="p-4 space-y-3">
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          accept=".pdf,image/*"
          onChange={(e) => {
            const list = e.target.files
            const replaceId = replaceIdRef.current
            replaceIdRef.current = null
            e.target.value = ''
            if (replaceId && list?.[0]) f.replaceFile(replaceId, list[0])
            else f.addFiles(list)
          }}
        />
        {f.files.length === 0 && (
          <div
            className={cn(
              'flex items-center gap-3 rounded-xl border border-dashed border-border/80 bg-bg-2/40 px-3 py-2.5 cursor-pointer',
              (f.running || f.uploading) && 'pointer-events-none opacity-60',
            )}
            onClick={() => { replaceIdRef.current = null; inputRef.current?.click() }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              replaceIdRef.current = null
              f.addFiles(e.dataTransfer?.files)
            }}
          >
            {f.uploading ? (
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-muted-foreground" />
            ) : (
              <Upload className="h-5 w-5 shrink-0 text-muted-foreground" />
            )}
            <div className="min-w-0 text-start">
              <p className="text-sm font-medium leading-tight">{t('drop')}</p>
              <p className="text-xs text-muted-foreground">{t('dropHint', { count: f.maxFiles })}</p>
            </div>
          </div>
        )}
        {f.files.length > 0 && (
          <ul className="space-y-1.5">
            {f.files.map((file) => (
              <li
                key={file.upload_id}
                className="flex items-center gap-2 rounded-lg border border-border/60 bg-background-elevated px-2.5 py-1.5"
              >
                <FileSearch className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate text-sm" dir="auto">{file.name}</span>
                {file.size != null && (
                  <span className="shrink-0 text-xs text-muted-foreground tabular-nums" dir="ltr">
                    {formatBytes(file.size)}
                  </span>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2"
                  disabled={f.running || f.uploading}
                  onClick={() => { replaceIdRef.current = file.upload_id; inputRef.current?.click() }}
                >
                  {t('fileChange')}
                </Button>
                <button
                  type="button"
                  className="inline-flex h-8 w-8 min-h-8 min-w-8 shrink-0 items-center justify-center rounded-md text-foreground-secondary hover:bg-background-tertiary hover:text-error"
                  disabled={f.running}
                  aria-label={t('fileRemove')}
                  onClick={() => f.setFiles((p) => p.filter((x) => x.upload_id !== file.upload_id))}
                >
                  <X className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
        {f.files.length > 0 && f.files.length < f.maxFiles && (
          <button
            type="button"
            className="text-sm text-accent hover:underline disabled:opacity-50"
            disabled={f.running || f.uploading}
            onClick={() => { replaceIdRef.current = null; inputRef.current?.click() }}
          >
            {t('fileAdd')}
          </button>
        )}
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="text-xs text-muted-foreground">{t('notes')}</label>
            <Textarea rows={3} value={f.notes} onChange={(e) => f.setNotes(e.target.value)} disabled={f.running} />
          </div>
          <select className="h-9 rounded-lg border border-border/60 bg-bg-2/50 px-2 text-sm" value={f.lang} onChange={(e) => f.setLang(e.target.value)}>
            <option value="fa">{t('lang.fa')}</option>
            <option value="en">{t('lang.en')}</option>
          </select>
        </div>
        <Button onClick={f.run} disabled={!f.files.length || f.running || f.uploading}>
          {f.running ? <Loader2 className="h-4 w-4 animate-spin me-2" /> : null}
          {t('run')}
        </Button>
      </Card>
      {r && (
        <Card className="p-4 space-y-4">
          <div className="flex justify-between items-start gap-2">
            <div className="text-sm">
              {resultDisclaimer ? <p className="font-medium">{resultDisclaimer}</p> : null}
            </div>
            <div className="flex gap-1 shrink-0">
              <Button type="button" size="icon" variant="ghost" onClick={copy} aria-label={t('common:actions.copy', { defaultValue: 'Copy' })}><Copy className="h-4 w-4" /></Button>
              <Button type="button" size="icon" variant="ghost" onClick={download} aria-label={t('common:actions.download', { defaultValue: 'Download' })}><Download className="h-4 w-4" /></Button>
            </div>
          </div>
          <p className="text-sm" dir="auto">{r.summary}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-start border-b border-border/50">
                  <th className="py-2 pe-2">{t('area')}</th>
                  <th className="py-2 pe-2">{t('level')}</th>
                  <th className="py-2 pe-2">{t('finding')}</th>
                  <th className="py-2">{t('recommendation')}</th>
                </tr>
              </thead>
              <tbody>
                {(r.risk_matrix || []).map((row, i) => (
                  <tr key={i} className="border-b border-border/30 align-top">
                    <td className="py-2 pe-2" dir="auto">{row.area}</td>
                    <td className="py-2 pe-2">
                      <span className={cn('rounded-full px-2 py-0.5 text-xs', LEVEL_CLASS[row.risk_level] || LEVEL_CLASS.medium)}>
                        {row.risk_level}
                      </span>
                    </td>
                    <td className="py-2 pe-2" dir="auto">{row.finding}</td>
                    <td className="py-2" dir="auto">{row.recommendation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!!r.key_clauses?.length && (
            <section>
              <h3 className="text-sm font-semibold mb-1">{t('clauses')}</h3>
              <ul className="list-disc ps-5 text-sm space-y-1" dir="auto">{r.key_clauses.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </section>
          )}
          {!!r.open_questions?.length && (
            <section>
              <h3 className="text-sm font-semibold mb-1">{t('openQuestions')}</h3>
              <ul className="list-disc ps-5 text-sm space-y-1" dir="auto">{r.open_questions.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </section>
          )}
          {!!r.red_flags?.length && (
            <section>
              <h3 className="text-sm font-semibold mb-1">{t('redFlags')}</h3>
              <ul className="list-disc ps-5 text-sm space-y-1 text-error" dir="auto">{r.red_flags.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </section>
          )}
        </Card>
      )}
      {f.budgetModal}
      {f.dlpModal}
    </PageShell>
  )
}

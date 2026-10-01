import { useRef } from 'react'
import { AlertTriangle, ClipboardList, Copy, Download, Loader2, Presentation, Upload, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Card } from '@/components/ui/card'
import useTenderFlow from '@/hooks/useTenderFlow'
import { cn } from '@/lib/utils'
import { fmtNumber } from '@/utils/persianLocale'

const STATUS_CLASS = {
  met: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  partial: 'bg-amber-500/15 text-amber-800 dark:text-amber-300',
  gap: 'bg-red-500/15 text-red-700 dark:text-red-300',
  unknown: 'bg-bg-2 text-muted-foreground',
}

function formatAmount(rial, unit) {
  if (rial == null || rial === '') return '—'
  const n = Number(rial)
  if (!Number.isFinite(n)) return String(rial)
  const display = unit === 'toman' ? Math.round(n / 10) : n
  return `${fmtNumber(display)} ${unit === 'toman' ? 'تومان' : 'ریال'}`
}

function toMarkdown(r, unit) {
  if (!r) return ''
  return [
    `# ${r.title || 'Tender pack'}`,
    '',
    r.summary || '',
    '',
    '## Compliance',
    ...(r.compliance_matrix || []).map(
      (row) => `- [${row.status}] ${row.requirement} — ${row.response || ''} ${row.amount_rial != null ? formatAmount(row.amount_rial, unit) : ''}`,
    ),
    '',
    '## Cover letter (FA)',
    r.cover_letter_fa || '',
    '',
    '## Questions',
    ...(r.questions || []).map((q) => `- ${q}`),
    '',
    '## Risks',
    ...(r.risks || []).map((q) => `- ${q}`),
  ].join('\n')
}

export default function TendersPage() {
  const { t } = useTranslation('tenders')
  const f = useTenderFlow()
  const inputRef = useRef(null)
  const r = f.result

  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text || '')
      toast.success(t('copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  return (
    <PageShell width="standard">
      <PageHeader
        icon={ClipboardList}
        title={t('title')}
        subtitle={t('subtitle')}
        actions={<PrivacyBadge mode="cloud" />}
      />
      <PrivacyBanner mode="cloud" />
      <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm" role="note">
        {t('disclaimer')}
      </div>
      {f.error && (
        <div className="flex gap-2 rounded-xl border border-error/30 bg-error/5 px-4 py-3 text-sm text-error">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{String(f.error)}</span>
        </div>
      )}
      <Card className="p-4 space-y-4">
        <div className="flex flex-wrap gap-2">
          {['tender', 'rfq'].map((m) => (
            <button key={m} type="button" className={cn('rounded-full border px-3 py-1 text-sm', f.mode === m ? 'border-accent bg-accent/10 text-accent' : 'border-border/60')} onClick={() => f.setMode(m)}>
              {t(`mode.${m}`)}
            </button>
          ))}
          {['toman', 'rial'].map((u) => (
            <button key={u} type="button" className={cn('rounded-full border px-3 py-1 text-sm', f.currencyUnit === u ? 'border-accent bg-accent/10 text-accent' : 'border-border/60')} onClick={() => f.setCurrencyUnit(u)}>
              {t(`currency.${u}`)}
            </button>
          ))}
          <select className="h-9 rounded-lg border border-border/60 bg-bg-2/50 px-2 text-sm ms-auto" value={f.lang} onChange={(e) => f.setLang(e.target.value)}>
            <option value="fa">{t('lang.fa')}</option>
            <option value="en">{t('lang.en')}</option>
          </select>
        </div>
        <div
          className="rounded-xl border border-dashed border-border/80 bg-bg-2/40 px-4 py-6 text-center cursor-pointer"
          onClick={() => !f.running && inputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); f.addFiles(e.dataTransfer?.files) }}
        >
          <Upload className="mx-auto h-7 w-7 text-muted-foreground mb-2" />
          <p className="text-sm font-medium">{t('drop')}</p>
          <input ref={inputRef} type="file" multiple className="hidden" accept=".pdf,.docx,.doc,.txt,image/*" onChange={(e) => { f.addFiles(e.target.files); e.target.value = '' }} />
        </div>
        <ul className="flex flex-wrap gap-2">
          {f.files.map((file) => (
            <li key={file.upload_id} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs">
              <span dir="auto">{file.name}</span>
              <button type="button" onClick={() => f.setFiles((p) => p.filter((x) => x.upload_id !== file.upload_id))} disabled={f.running}><X className="h-3 w-3" /></button>
            </li>
          ))}
        </ul>
        <div>
          <label className="text-xs text-muted-foreground">{t('notes')}</label>
          <Textarea rows={3} value={f.notes} onChange={(e) => f.setNotes(e.target.value)} disabled={f.running} />
        </div>
        <Button onClick={f.run} disabled={!f.files.length || f.running || f.uploading}>
          {f.running ? <Loader2 className="h-4 w-4 animate-spin me-2" /> : null}
          {t('run')}
        </Button>
      </Card>
      {r && (
        <div className="space-y-4">
          <Card className="p-4 space-y-2">
            <div className="flex justify-between gap-2">
              <h2 className="text-base font-semibold" dir="auto">{r.title || t('result')}</h2>
              <div className="flex gap-1">
                <Button type="button" size="icon" variant="ghost" aria-label={t('common:actions.copy', { defaultValue: 'Copy' })} onClick={() => copy(toMarkdown(r, f.currencyUnit))}><Copy className="h-4 w-4" /></Button>
                <Button type="button" size="icon" variant="ghost" aria-label={t('common:actions.download', { defaultValue: 'Download' })} onClick={() => {
                  const blob = new Blob([toMarkdown(r, f.currencyUnit)], { type: 'text/markdown;charset=utf-8' })
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = 'tender-pack.md'
                  a.click()
                  URL.revokeObjectURL(url)
                }}><Download className="h-4 w-4" /></Button>
                {f.canHandoff && (
                  <Button type="button" variant="outline" size="sm" onClick={f.handoff}>
                    <Presentation className="h-4 w-4 me-1" />
                    {t('handoff')}
                  </Button>
                )}
              </div>
            </div>
            <p className="text-sm" dir="auto">{r.summary}</p>
          </Card>
          <Card className="p-4 overflow-x-auto">
            <h3 className="text-sm font-semibold mb-2">{t('matrix')}</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-start">
                  <th className="py-2 pe-2">ID</th>
                  <th className="py-2 pe-2">{t('requirement')}</th>
                  <th className="py-2 pe-2">{t('status')}</th>
                  <th className="py-2 pe-2">{t('response')}</th>
                  <th className="py-2">{t('amount')}</th>
                </tr>
              </thead>
              <tbody>
                {(r.compliance_matrix || []).map((row) => (
                  <tr key={row.id || row.requirement} className="border-b border-border/30 align-top">
                    <td className="py-2 pe-2" dir="ltr">{row.id}</td>
                    <td className="py-2 pe-2" dir="auto">{row.requirement}</td>
                    <td className="py-2 pe-2">
                      <span className={cn('rounded-full px-2 py-0.5 text-xs', STATUS_CLASS[row.status] || STATUS_CLASS.unknown)}>{row.status}</span>
                    </td>
                    <td className="py-2 pe-2" dir="auto">{row.response}</td>
                    <td className="py-2" dir="ltr">{formatAmount(row.amount_rial, f.currencyUnit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          {r.cover_letter_fa && (
            <Card className="p-4 space-y-2">
              <div className="flex justify-between">
                <h3 className="text-sm font-semibold">{t('coverLetter')}</h3>
                <Button type="button" size="sm" variant="ghost" onClick={() => copy(r.cover_letter_fa)}><Copy className="h-4 w-4" /></Button>
              </div>
              <pre className="whitespace-pre-wrap text-sm font-sans" dir="auto">{r.cover_letter_fa}</pre>
            </Card>
          )}
          {!!r.questions?.length && (
            <Card className="p-4">
              <h3 className="text-sm font-semibold mb-2">{t('questions')}</h3>
              <ul className="list-disc ps-5 text-sm space-y-1" dir="auto">{r.questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
            </Card>
          )}
          {!!r.risks?.length && (
            <Card className="p-4">
              <h3 className="text-sm font-semibold mb-2">{t('risks')}</h3>
              <ul className="list-disc ps-5 text-sm space-y-1" dir="auto">{r.risks.map((q, i) => <li key={i}>{q}</li>)}</ul>
            </Card>
          )}
        </div>
      )}
      {f.budgetModal}
      {f.dlpModal}
    </PageShell>
  )
}

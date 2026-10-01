import {
  AlertTriangle,
  Check,
  Circle,
  Copy,
  Download,
  ExternalLink,
  Loader2,
  ShoppingCart,
  Square,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card } from '@/components/ui/card'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer'
import useShopFlow, { SHOP_PIPELINE } from '@/hooks/useShopFlow'
import { cn } from '@/lib/utils'
import { fmtNumber } from '@/utils/persianLocale'

const CATEGORIES = ['auto', 'office', 'it']

function formatElapsed(s) {
  const n = Math.max(0, Number(s) || 0)
  const m = Math.floor(n / 60)
  const r = n % 60
  return m > 0 ? `${m}:${String(r).padStart(2, '0')}` : `0:${String(r).padStart(2, '0')}`
}

function merchantLabel(t, id) {
  return t(`merchants.${id}`, { defaultValue: id })
}

function priceToman(n) {
  if (n == null || n === '') return '—'
  return fmtNumber(Number(n))
}

function ShopActivity({ running, status, activity, elapsedS, error, t }) {
  if (!running && !activity.length && !error) return null
  const activePhase = status?.phase || activity[activity.length - 1]?.phase
  const activeIdx = SHOP_PIPELINE.indexOf(activePhase)
  const failed = !running && !!error

  return (
    <Card
      className={cn(
        'p-4 space-y-4',
        failed ? 'border-error/30 bg-error/[0.04]' : 'border-accent/20 bg-accent/[0.03]',
      )}
      aria-live="polite"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          {running ? (
            <Loader2 className="h-4 w-4 animate-spin text-accent shrink-0" aria-hidden />
          ) : failed ? (
            <AlertTriangle className="h-4 w-4 text-error shrink-0" aria-hidden />
          ) : (
            <Check className="h-4 w-4 text-success shrink-0" aria-hidden />
          )}
          <div className="min-w-0">
            <p className={cn('text-sm font-semibold truncate', failed && 'text-error')}>
              {running
                ? t(`status.${activePhase}`, { defaultValue: t('activity.working') })
                : failed
                  ? t('activity.failed')
                  : t('activity.done')}
            </p>
            <p className="text-xs text-muted-foreground">{failed ? String(error) : t('activity.hint')}</p>
          </div>
        </div>
        <div className="text-end shrink-0" dir="ltr">
          <p className="text-lg font-semibold tabular-nums tracking-tight text-accent">
            {formatElapsed(elapsedS)}
          </p>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
            {t('activity.elapsed')}
          </p>
        </div>
      </div>

      <ol className="space-y-1.5">
        {SHOP_PIPELINE.filter((p) => p !== 'done').map((phase, i) => {
          const done = activeIdx > i || (!running && activity.some((a) => a.phase === phase))
          const current = running && activePhase === phase
          return (
            <li
              key={phase}
              className={cn(
                'flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors',
                current && 'bg-accent/10 text-accent font-medium',
                done && !current && 'text-muted-foreground',
                !done && !current && 'text-muted-foreground/60',
              )}
            >
              {current ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" aria-hidden />
              ) : done ? (
                <Check className="h-3.5 w-3.5 text-success shrink-0" aria-hidden />
              ) : (
                <Circle className="h-3.5 w-3.5 shrink-0 opacity-40" aria-hidden />
              )}
              <span className="flex-1 min-w-0">{t(`status.${phase}`)}</span>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

function ProductCard({ item, t, badge }) {
  if (!item) return null
  const specs = item.specs && typeof item.specs === 'object' ? Object.entries(item.specs).slice(0, 8) : []
  return (
    <Card className="p-4 space-y-2">
      {badge && (
        <span className="inline-flex rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-semibold text-accent">
          {badge}
        </span>
      )}
      <p className="text-sm font-semibold leading-snug" dir="auto">{item.title}</p>
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        <span>{merchantLabel(t, item.merchant)}</span>
        {item.brand && <span dir="auto">{item.brand}</span>}
        {item.warranty && <span dir="auto">{item.warranty}</span>}
        <span dir="ltr">
          {t('unitPrice')}: {priceToman(item.unit_price_toman)}
        </span>
        <span dir="ltr" className="font-semibold text-foreground">
          {t('totalPrice')}: {priceToman(item.total_toman)}
        </span>
      </div>
      {specs.length > 0 && (
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-muted-foreground border-t border-border/40 pt-2">
          {specs.map(([k, v]) => (
            <div key={k} className="min-w-0 flex gap-1" dir="auto">
              <dt className="font-medium text-foreground/70 shrink-0">{k}:</dt>
              <dd className="truncate">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {item.why && (
        <p className="text-xs text-muted-foreground" dir="auto">
          <span className="font-medium text-foreground/80">{t('why')}: </span>
          {item.why}
        </p>
      )}
      {item.url && (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
        >
          {t('openLink')}
          <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </Card>
  )
}

export default function ShopPage() {
  const { t } = useTranslation('shop')
  const f = useShopFlow()

  const copyMd = async () => {
    try {
      await navigator.clipboard.writeText(f.result?.report_md || '')
      toast.success(t('copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  const downloadMd = () => {
    const blob = new Blob([f.result?.report_md || ''], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'shop-report.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  const downloadCsv = () => {
    const rows = f.result?.all_candidates || []
    const header = ['title', 'merchant', 'unit_price_toman', 'total_toman', 'url']
    const lines = [header.join(',')]
    for (const r of rows) {
      const cells = header.map((k) => {
        const v = String(r[k] ?? '').replace(/"/g, '""')
        return `"${v}"`
      })
      lines.push(cells.join(','))
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'shop-compare.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  const canRun = !!f.need.trim() && !f.running
  const hasResult = !!f.result
  const emptyDone = hasResult && !f.result.winner && !(f.result.all_candidates || []).length

  return (
    <PageShell width="wide">
      <PageHeader
        icon={ShoppingCart}
        title={t('title')}
        subtitle={t('subtitle')}
        actions={<PrivacyBadge mode="cloud" />}
      />
      <PrivacyBanner mode="cloud" />

      {f.error && !f.running && (
        <div className="flex gap-2 rounded-xl border border-error/30 bg-error/5 px-4 py-3 text-sm text-error">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{String(f.error)}</span>
        </div>
      )}

      <Card className="p-4 space-y-4">
        <p className="text-xs text-muted-foreground">{t('merchantsNote')}</p>

        <div className="flex flex-wrap gap-2 items-center">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              type="button"
              disabled={f.running}
              className={cn(
                'rounded-full border px-3 py-1 text-sm transition-colors',
                f.category === c ? 'border-accent bg-accent/10 text-accent' : 'border-border/60',
                f.running && 'opacity-60',
              )}
              onClick={() => f.setCategory(c)}
            >
              {t(`categoryOptions.${c}`)}
            </button>
          ))}
          <select
            className="h-9 rounded-lg border border-border/60 bg-bg-2 px-2 text-sm ms-auto"
            value={f.lang}
            onChange={(e) => f.setLang(e.target.value)}
            disabled={f.running}
          >
            <option value="fa">{t('lang.fa')}</option>
            <option value="en">{t('lang.en')}</option>
          </select>
        </div>

        <div>
          <label className="text-xs font-medium text-muted-foreground">{t('need')}</label>
          <Textarea
            className="mt-1"
            rows={3}
            value={f.need}
            onChange={(e) => f.setNeed(e.target.value)}
            disabled={f.running}
            dir="auto"
            placeholder={t('needPlaceholder')}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="text-xs font-medium text-muted-foreground">{t('qty')}</label>
            <Input
              className="mt-1"
              type="number"
              min={1}
              max={9999}
              dir="ltr"
              value={f.qty}
              onChange={(e) => f.setQty(e.target.value)}
              disabled={f.running}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">{t('maxBudget')}</label>
            <Input
              className="mt-1"
              type="text"
              inputMode="numeric"
              dir="ltr"
              value={f.maxBudget}
              onChange={(e) => f.setMaxBudget(e.target.value)}
              disabled={f.running}
              placeholder="—"
            />
            <p className="mt-1 text-[11px] text-muted-foreground">{t('maxBudgetHint')}</p>
          </div>
        </div>

        <div>
          <label className="text-xs font-medium text-muted-foreground">{t('notes')}</label>
          <Textarea
            className="mt-1"
            rows={2}
            value={f.notes}
            onChange={(e) => f.setNotes(e.target.value)}
            disabled={f.running}
            dir="auto"
            placeholder={t('notesPlaceholder')}
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <Button onClick={f.run} disabled={!canRun}>
            {f.running ? <Loader2 className="h-4 w-4 animate-spin me-2" /> : null}
            {f.running ? t('running') : t('run')}
          </Button>
          {f.running && (
            <Button type="button" variant="outline" onClick={f.cancel}>
              <Square className="h-3.5 w-3.5 me-2" />
              {t('cancel')}
            </Button>
          )}
        </div>
      </Card>

      <ShopActivity
        running={f.running}
        status={f.status}
        activity={f.activity}
        elapsedS={f.elapsedS}
        error={f.error}
        t={t}
      />

      {f.running && f.liveCandidates.length > 0 && (
        <Card className="p-4 space-y-2">
          <p className="text-sm font-medium">{t('liveHits')} ({f.liveCandidates.length})</p>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {f.liveCandidates.slice(0, 8).map((c) => (
              <li key={c.url} className="flex gap-2 min-w-0">
                <span className="shrink-0">{merchantLabel(t, c.merchant)}</span>
                <span className="truncate" dir="auto">{c.title}</span>
                <span className="ms-auto shrink-0 tabular-nums" dir="ltr">
                  {priceToman(c.unit_price_toman)}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {hasResult && (
        <div className="space-y-4">
          {(f.result.disclaimer || f.result.summary) && (
            <Card className="p-4 space-y-2">
              {f.result.summary && (
                <div>
                  <p className="text-sm font-medium mb-1">{t('summary')}</p>
                  <p className="text-sm text-muted-foreground" dir="auto">{f.result.summary}</p>
                </div>
              )}
              {f.result.disclaimer && (
                <p className="text-[11px] text-muted-foreground border-t border-border/40 pt-2" dir="auto">
                  {f.result.disclaimer}
                </p>
              )}
              <div className="flex flex-wrap gap-1 pt-1">
                <Button type="button" size="sm" variant="outline" onClick={copyMd} disabled={!f.result.report_md}>
                  <Copy className="h-3.5 w-3.5 me-1" />
                  {t('copyMd')}
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={downloadMd} disabled={!f.result.report_md}>
                  <Download className="h-3.5 w-3.5 me-1" />
                  {t('downloadMd')}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={downloadCsv}
                  disabled={!(f.result.all_candidates || []).length}
                >
                  <Download className="h-3.5 w-3.5 me-1" />
                  {t('downloadCsv')}
                </Button>
              </div>
            </Card>
          )}

          {emptyDone ? (
            <Card className="p-4 text-sm text-muted-foreground">{t('noResults')}</Card>
          ) : (
            <>
              {f.result.winner && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">{t('winner')}</p>
                  <ProductCard item={f.result.winner} t={t} badge={t('winner')} />
                </div>
              )}

              {(f.result.alternatives || []).length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">{t('alternatives')}</p>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {(f.result.alternatives || []).map((a) => (
                      <ProductCard key={a.url || a.title} item={a} t={t} />
                    ))}
                  </div>
                </div>
              )}

              {(f.result.all_candidates || []).length > 0 && (
                <Card className="p-4 space-y-3 overflow-x-auto">
                  <p className="text-sm font-medium">{t('table')}</p>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50 text-start text-xs text-muted-foreground">
                        <th className="py-2 pe-3 font-medium">{t('need')}</th>
                        <th className="py-2 pe-3 font-medium">{t('merchant')}</th>
                        <th className="py-2 pe-3 font-medium">{t('unitPrice')}</th>
                        <th className="py-2 pe-3 font-medium">{t('totalPrice')}</th>
                        <th className="py-2 font-medium" />
                      </tr>
                    </thead>
                    <tbody>
                      {(f.result.all_candidates || []).map((row) => (
                        <tr key={row.url || row.title} className="border-b border-border/30">
                          <td className="py-2 pe-3 max-w-[16rem]" dir="auto">
                            <span className="line-clamp-2">{row.title}</span>
                          </td>
                          <td className="py-2 pe-3 whitespace-nowrap">
                            {merchantLabel(t, row.merchant)}
                          </td>
                          <td className="py-2 pe-3 tabular-nums" dir="ltr">
                            {priceToman(row.unit_price_toman)}
                          </td>
                          <td className="py-2 pe-3 tabular-nums font-medium" dir="ltr">
                            {priceToman(row.total_toman)}
                          </td>
                          <td className="py-2">
                            {row.url && (
                              <a
                                href={row.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex text-accent"
                                aria-label={t('openLink')}
                              >
                                <ExternalLink className="h-4 w-4" />
                              </a>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              )}

              {f.result.report_md && (
                <Card className="p-4">
                  <MarkdownRenderer content={f.result.report_md} />
                </Card>
              )}
            </>
          )}
        </div>
      )}

      {f.budgetModal}
      {f.dlpModal}
    </PageShell>
  )
}

import { useMemo, useState } from 'react'
import { Copy, Download, RotateCcw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer'
import ResearchSources from './ResearchSources'
import { cn } from '@/lib/utils'

function formatElapsed(s) {
  if (s == null || Number.isNaN(Number(s))) return null
  const n = Math.max(0, Number(s) || 0)
  const m = Math.floor(n / 60)
  const r = n % 60
  return m > 0 ? `${m}:${String(r).padStart(2, '0')}` : `0:${String(r).padStart(2, '0')}`
}

/** "1. **عنوان**" → "## عنوان" so prose renders real section breaks. */
function normalizeReportMd(md) {
  if (!md) return ''
  return String(md).replace(
    /^[ \t]*(?:\d+[\.\)]|[۰-۹]+[\.\)])\s*\*\*(.+?)\*\*\s*$/gm,
    '## $1',
  )
}

/**
 * Report reader: sticky actions, desktop sources rail, mobile tabs.
 */
export default function ResearchReport({
  report,
  citations,
  meta,
  mode,
  downloadName,
  elapsedS,
  onNew,
  className,
}) {
  const { t } = useTranslation('research')
  const [tab, setTab] = useState('report')
  const duration = formatElapsed(meta?.elapsed_s ?? elapsedS)
  const hasSources = Array.isArray(citations) && citations.length > 0
  const reportMd = useMemo(() => normalizeReportMd(report), [report])

  const modeLabel = useMemo(() => {
    const m = meta?.mode || mode
    if (!m) return null
    return t(`mode.${m}`, { defaultValue: m })
  }, [meta?.mode, mode, t])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(reportMd || '')
      toast.success(t('copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  const download = () => {
    const blob = new Blob([reportMd || ''], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${downloadName || 'research-report'}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const actionBar = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-2 min-w-0">
        <p className="text-sm font-semibold">{t('report')}</p>
        <div className="flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
          {modeLabel && (
            <span className="rounded-md bg-bg-3 px-1.5 py-0.5">
              {t('meta.mode')}: {modeLabel}
            </span>
          )}
          {meta?.model_id && (
            <span className="rounded-md bg-bg-3 px-1.5 py-0.5" dir="ltr">
              {meta.model_id}
            </span>
          )}
          {duration && (
            <span className="rounded-md bg-bg-3 px-1.5 py-0.5" dir="ltr">
              {t('meta.elapsed')}: {duration}
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1 shrink-0">
        <Button type="button" size="sm" variant="ghost" onClick={copy} disabled={!reportMd}>
          <Copy className="h-4 w-4 me-1.5" />
          <span className="text-xs">{t('actions.copy')}</span>
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={download} disabled={!reportMd}>
          <Download className="h-4 w-4 me-1.5" />
          <span className="text-xs">{t('actions.download')}</span>
        </Button>
        {onNew && (
          <Button type="button" size="sm" variant="outline" onClick={onNew}>
            <RotateCcw className="h-3.5 w-3.5 me-1.5" />
            <span className="text-xs">{t('newResearch')}</span>
          </Button>
        )}
      </div>
    </div>
  )

  const body = (
    <div
      className={cn(
        'prose prose-sm dark:prose-invert max-w-none',
        // Real ## sections need breathing room (model used to dump numbered bold labels)
        'prose-headings:scroll-mt-20 prose-h2:mt-8 prose-h2:mb-3 prose-h2:text-base prose-h2:font-semibold',
        'prose-h3:mt-5 prose-h3:mb-2 prose-h3:text-sm',
        'prose-p:leading-7 prose-li:my-1',
      )}
      dir="auto"
    >
      <MarkdownRenderer content={reportMd} />
    </div>
  )

  return (
    <div className={cn('space-y-3', className)}>
      <div className="hidden lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(240px,280px)] lg:gap-4 lg:items-start">
        <Card className="p-4 space-y-4 min-w-0">
          {actionBar}
          {body}
        </Card>
        <aside className="sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto">
          <Card className="p-4">
            <ResearchSources citations={citations} />
          </Card>
        </aside>
      </div>

      <div className="lg:hidden">
        <Card className="p-4 space-y-3">
          {actionBar}
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="w-full">
              <TabsTrigger value="report" className="flex-1">
                {t('tabs.report')}
              </TabsTrigger>
              <TabsTrigger value="sources" className="flex-1">
                {t('tabs.sources')}
                {hasSources ? ` (${citations.length})` : ''}
              </TabsTrigger>
            </TabsList>
            <TabsContent value="report" className="mt-3">
              {body}
            </TabsContent>
            <TabsContent value="sources" className="mt-3">
              <ResearchSources citations={citations} />
            </TabsContent>
          </Tabs>
        </Card>
      </div>
    </div>
  )
}

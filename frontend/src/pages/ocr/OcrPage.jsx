import { useCallback, useRef, useState } from 'react'
import {
  AlertTriangle,
  Copy,
  Download,
  FileText,
  History,
  Loader2,
  ScanText,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import HeaderSlot from '@/components/layout/HeaderSlot'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Card } from '@/components/ui/card'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer'
import useOcrFlow from '@/hooks/useOcrFlow'
import { cn } from '@/lib/utils'
import OcrHistoryRail from './OcrHistoryRail'

function downloadText(name, text) {
  const base = (name || 'extract').replace(/\.[^.]+$/, '')
  const blob = new Blob([text || ''], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${base}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function ResultCard({ item, t }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(item.content || '')
      toast.success(t('result.copied'))
    } catch {
      toast.error(t('errors.generic'))
    }
  }

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex items-center gap-2">
          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate text-sm font-medium" dir="auto">
            {item.original_name || item.upload_id}
          </span>
          {item.status === 'pending' && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          )}
          {item.status === 'error' && (
            <span className="text-xs text-error">{t('result.failed')}</span>
          )}
        </div>
        {item.status === 'ok' && item.content && (
          <div className="flex shrink-0 gap-1">
            <Button type="button" size="icon" variant="ghost" onClick={copy} aria-label={t('result.copy')}>
              <Copy className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              onClick={() => downloadText(item.original_name, item.content)}
              aria-label={t('result.download')}
            >
              <Download className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>
      {item.status === 'error' && (
        <p className="text-sm text-error" dir="auto">
          {item.error}
        </p>
      )}
      {item.status === 'ok' && item.content && (
        <div className="prose prose-sm dark:prose-invert max-w-none border-t border-border/40 pt-3">
          <MarkdownRenderer content={item.content} />
        </div>
      )}
      {item.status === 'pending' && (
        <p className="text-sm text-muted-foreground">{t('result.waiting')}</p>
      )}
    </Card>
  )
}

export default function OcrPage() {
  const { t } = useTranslation('ocr')
  const f = useOcrFlow()
  const inputRef = useRef(null)
  const [historyOpen, setHistoryOpen] = useState(false)

  const onDrop = useCallback(
    (e) => {
      e.preventDefault()
      e.stopPropagation()
      if (f.running || f.uploading) return
      f.addFiles(e.dataTransfer?.files)
    },
    [f],
  )

  const onPick = useCallback(
    (e) => {
      f.addFiles(e.target.files)
      e.target.value = ''
    },
    [f],
  )

  return (
    <div className="h-full flex">
      <div className="hidden md:flex flex-col w-[280px] shrink-0">
        <OcrHistoryRail
          jobs={f.jobs}
          currentJobId={f.currentJobId}
          onNew={f.newJob}
          onLoad={f.loadJob}
          onDelete={f.removeJob}
        />
      </div>

      <HeaderSlot side="end">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setHistoryOpen(true)}
          className="md:hidden shrink-0"
          aria-label={t('history.title')}
          title={t('history.title')}
        >
          <History className="h-5 w-5" />
        </Button>
      </HeaderSlot>

      <div className="flex-1 min-w-0 overflow-y-auto">
        <PageShell width="standard">
      <PageHeader
        icon={ScanText}
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
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">{String(f.error)}</span>
        </div>
      )}

      <Card className="p-4 sm:p-5 space-y-4">
        <div
          className={cn(
            'rounded-xl border border-dashed border-border/80 bg-bg-2/40 px-4 py-8 text-center transition-colors',
            !f.running && !f.uploading && 'hover:border-accent/50 cursor-pointer',
          )}
          onDragOver={(e) => {
            e.preventDefault()
            e.stopPropagation()
          }}
          onDrop={onDrop}
          onClick={() => {
            if (!f.running && !f.uploading) inputRef.current?.click()
          }}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              if (!f.running && !f.uploading) inputRef.current?.click()
            }
          }}
        >
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            accept="image/png,image/jpeg,image/webp,image/gif,application/pdf,.pdf,.png,.jpg,.jpeg,.webp,.gif"
            multiple
            onChange={onPick}
            disabled={f.running || f.uploading}
          />
          <Upload className="mx-auto h-8 w-8 text-muted-foreground mb-2" aria-hidden />
          <p className="text-sm font-medium">{t('drop.title')}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {t('drop.hint', { count: f.maxFiles })}
          </p>
          {f.uploading && (
            <p className="text-xs text-muted-foreground mt-2 flex items-center justify-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              {t('drop.uploading')}
            </p>
          )}
        </div>

        {f.files.length > 0 && (
          <ul className="flex flex-wrap gap-2">
            {f.files.map((file) => (
              <li
                key={file.upload_id}
                className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border/60 bg-bg-2/60 px-3 py-1 text-xs"
              >
                <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                <span className="truncate max-w-[12rem]" dir="auto">
                  {file.name}
                </span>
                <button
                  type="button"
                  className="rounded-full p-0.5 hover:bg-bg-3 disabled:opacity-40"
                  onClick={(e) => {
                    e.stopPropagation()
                    f.removeFile(file.upload_id)
                  }}
                  disabled={f.running}
                  aria-label={t('drop.remove')}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="ocr-prompt">
            {t('prompt.label')}
          </label>
          <Textarea
            id="ocr-prompt"
            value={f.prompt}
            onChange={(e) => f.setPrompt(e.target.value)}
            placeholder={t('prompt.placeholder')}
            rows={3}
            disabled={f.running}
            dir="auto"
          />
          <p className="text-xs text-muted-foreground">{t('prompt.hint')}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            onClick={f.extract}
            disabled={!f.files.length || f.running || f.uploading}
            className="gap-2"
          >
            {f.running ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {f.progress
                  ? t('actions.extracting', {
                      done: (f.progress.done || 0) + 1,
                      total: f.progress.total || f.files.length,
                    })
                  : t('actions.working')}
              </>
            ) : (
              <>
                <ScanText className="h-4 w-4" />
                {t('actions.extract')}
              </>
            )}
          </Button>
          {f.running && (
            <Button type="button" variant="outline" onClick={f.cancel}>
              {t('actions.cancel')}
            </Button>
          )}
          {f.results.length > 0 && !f.running && (
            <Button type="button" variant="ghost" className="gap-1.5" onClick={f.clearResults}>
              <Trash2 className="h-4 w-4" />
              {t('actions.clearResults')}
            </Button>
          )}
        </div>
      </Card>

      {f.results.length > 0 && (
        <section className="space-y-3" aria-label={t('result.section')}>
          <h2 className="text-sm font-semibold text-muted-foreground">{t('result.section')}</h2>
          {f.results.map((item) => (
            <ResultCard key={item.upload_id} item={item} t={t} />
          ))}
        </section>
      )}

      {f.budgetModal}
      {f.dlpModal}
        </PageShell>
      </div>

      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent side="start" className="p-0 w-[85vw] sm:max-w-sm">
          <SheetTitle className="sr-only">{t('history.title')}</SheetTitle>
          <OcrHistoryRail
            jobs={f.jobs}
            currentJobId={f.currentJobId}
            onNew={() => {
              f.newJob()
              setHistoryOpen(false)
            }}
            onLoad={(id) => {
              f.loadJob(id)
              setHistoryOpen(false)
            }}
            onDelete={f.removeJob}
          />
        </SheetContent>
      </Sheet>
    </div>
  )
}

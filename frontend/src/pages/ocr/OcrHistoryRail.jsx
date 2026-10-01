import { Plus, Clock, Trash2, FileText } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'
import { cn } from '@/lib/utils'
import { fmtDistanceToNow } from '@/utils/dateLocale'

function JobItem({ job, isActive, onLoad, onDelete }) {
  const { t } = useTranslation('ocr')
  const { confirm, confirmDialog } = useConfirmDelete()
  const relativeTime = job.created_at
    ? fmtDistanceToNow(new Date(job.created_at), { addSuffix: true })
    : ''
  const fileCount = Array.isArray(job.files) ? job.files.length : 0

  const handleDelete = async (e) => {
    e.stopPropagation()
    const ok = await confirm({
      title: t('history.deleteTitle'),
      description: t('history.deleteConfirm'),
      destructive: true,
    })
    if (ok) onDelete(job._id)
  }

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={() => onLoad(job._id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onLoad(job._id)
          }
        }}
        className={cn(
          'group w-full text-start flex flex-col gap-1.5 p-3 rounded-[9px] cursor-pointer transition-colors',
          isActive
            ? 'bg-accent/10 text-accent-hover ring-1 ring-inset ring-accent/30'
            : 'text-foreground-secondary hover:bg-background-tertiary',
        )}
      >
        <div className="flex items-start justify-between gap-1">
          <p className="text-sm text-foreground line-clamp-2 leading-snug min-w-0" dir="auto">
            {job.title || t('history.untitled')}
          </p>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={handleDelete}
                className="inline-flex h-8 w-8 min-h-8 min-w-8 shrink-0 items-center justify-center rounded-md text-foreground-secondary hover:bg-background-tertiary hover:text-error focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={t('history.deleteFromHistory')}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">{t('history.deleteFromHistory')}</TooltipContent>
          </Tooltip>
        </div>
        <div className="flex items-center gap-2 text-xs text-foreground-tertiary">
          {fileCount > 0 && (
            <span className="inline-flex items-center gap-1">
              <FileText className="h-3 w-3" />
              {t('history.fileCount', { count: fileCount })}
            </span>
          )}
          {relativeTime && (
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {relativeTime}
            </span>
          )}
        </div>
      </div>
      {confirmDialog}
    </>
  )
}

export default function OcrHistoryRail({ jobs, currentJobId, onNew, onLoad, onDelete }) {
  const { t } = useTranslation('ocr')
  return (
    <div className="flex flex-col h-full border-e border-border bg-background-secondary">
      <div className="flex flex-col gap-2 p-3 border-b border-border">
        <h2 className="text-[11px] font-bold uppercase tracking-wider text-foreground-tertiary">
          {t('history.title')}
        </h2>
        <Button size="sm" onClick={onNew} className="w-full gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          {t('history.new')}
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {jobs.length === 0 ? (
          <p className="text-xs text-foreground-tertiary text-center py-6">{t('history.empty')}</p>
        ) : (
          jobs.map((job) => (
            <JobItem
              key={job._id}
              job={job}
              isActive={currentJobId === job._id}
              onLoad={onLoad}
              onDelete={onDelete}
            />
          ))
        )}
      </div>
    </div>
  )
}

import { Trash2, Plus, Clock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'
import { cn } from '../../../utils/cn'
import { fmtDistanceToNow } from '../../../utils/dateLocale'

// Unified status vocabulary across the section: warning / accent / success /
// error / foreground-secondary (no bespoke warn/ok/err/fg-3 aliases).
const STATUS_STYLES = {
  pending:    'bg-warning/15 text-warning border-warning/30',
  running:    'bg-accent/15 text-accent border-accent/30',
  completed:  'bg-success/15 text-success border-success/30',
  error:      'bg-error/15 text-error border-error/30',
  stopped:    'bg-foreground-secondary/15 text-foreground-secondary border-foreground-secondary/30',
  timed_out:  'bg-warning/15 text-warning border-warning/30',
}

function TaskItem({ task, isActive, onLoad, onDelete }) {
  const { t } = useTranslation('automate')
  const { confirm, confirmDialog } = useConfirmDelete()
  const relativeTime = task.created_at
    ? fmtDistanceToNow(new Date(task.created_at), { addSuffix: true })
    : ''

  const handleDelete = async (e) => {
    e.stopPropagation()
    const ok = await confirm({
      title: t('sidebar.deleteTitle'),
      description: t('sidebar.deleteConfirm'),
      destructive: true,
    })
    if (ok) onDelete(task._id)
  }

  return (
    <>
    <div
      onClick={() => onLoad(task._id)}
      className={cn(
        'group flex flex-col gap-1.5 p-3 rounded-[9px] cursor-pointer transition-colors',
        isActive
          ? 'bg-accent/10 text-accent-hover ring-1 ring-inset ring-accent/30'
          : 'text-foreground-secondary hover:bg-background-tertiary'
      )}
    >
      <div className="flex items-center justify-between gap-1">
        <Badge variant="outline" className={cn('text-xs capitalize shrink-0', STATUS_STYLES[task.status] || STATUS_STYLES.stopped)}>
          {task.status}
        </Badge>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleDelete}
          className="h-6 w-6 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 transition-opacity text-foreground-tertiary hover:text-error"
          title={t('sidebar.deleteTitle')}
          aria-label={t('sidebar.deleteTitle')}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>

      <p className="text-sm text-foreground line-clamp-2 leading-snug">
        {task.task_text}
      </p>

      {relativeTime && (
        <div className="flex items-center gap-1 text-xs text-foreground-tertiary">
          <Clock className="h-3 w-3" />
          {relativeTime}
        </div>
      )}
    </div>
    {confirmDialog}
    </>
  )
}

export default function TaskHistorySidebar({ tasks, currentTask, onNewTask, onLoadTask, onDeleteTask }) {
  const { t } = useTranslation('automate')
  return (
    <div className="flex flex-col h-full border-e border-border bg-background-secondary">
      {/* Header — canonical rail group header + full-width accent new-item button */}
      <div className="flex flex-col gap-2 p-3 border-b border-border">
        <h2 className="text-[11px] font-bold uppercase tracking-wider text-foreground-tertiary">
          {t('sidebar.title')}
        </h2>
        <Button size="sm" onClick={onNewTask} className="w-full gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          {t('sidebar.new')}
        </Button>
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {tasks.length === 0 ? (
          <p className="text-xs text-foreground-tertiary text-center py-6">{t('sidebar.noTasks')}</p>
        ) : (
          tasks.map((task) => (
            <TaskItem
              key={task._id}
              task={task}
              isActive={currentTask?._id === task._id}
              onLoad={onLoadTask}
              onDelete={onDeleteTask}
            />
          ))
        )}
      </div>
    </div>
  )
}

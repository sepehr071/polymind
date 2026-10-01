import { useCallback, useState } from 'react'
import { Bot, CheckCircle2, XCircle, AlertCircle, StopCircle, History, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import HeaderSlot from '@/components/layout/HeaderSlot'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { cn } from '../../utils/cn'
import { useAutomateAgentState } from './hooks/useAutomateAgentState'
import TaskInput from './components/TaskInput'
import LiveBrowserFrame from './components/LiveBrowserFrame'
import EventStream from './components/EventStream'
import TaskHistorySidebar from './components/TaskHistorySidebar'
import { useDlpConfirm } from '../../hooks/useDlpConfirm'
import { useBudgetBlock } from '../../hooks/useBudgetBlock'

export default function AutomateAgentPage() {
  const { t } = useTranslation('automate')
  const { t: tc } = useTranslation('common')

  // Budget/credit 402 catcher (hard block — no resend). The structured 402
  // body ({code, scope, remaining, limit}) is forwarded by the state hook's
  // stream onError via `onBudgetError`. Declared before the state hook so the
  // handler can be wired into it.
  const { handleBudgetError, budgetModal } = useBudgetBlock()

  const state = useAutomateAgentState({ onBudgetError: handleBudgetError })
  const {
    currentTask, status, liveUrl, messages, taskHistory,
    selectedModel, taskInput, error,
    setSelectedModel, setTaskInput,
    runTask, stopTask, loadTask, deleteTask, newTask,
  } = state

  // DLP pre-flight + violation modal (workspace Content Safety policy).
  const { scan: dlpScan, dlpModal } = useDlpConfirm({ source: 'automate' })

  // Mobile-only task-history Sheet (the desktop rail is hidden below md, so
  // without this past tasks would be unreachable on phones). Loading a task
  // from the Sheet auto-closes it so the result is visible.
  const [historyOpen, setHistoryOpen] = useState(false)

  // Event-stream rail is collapsible on wide screens so the live browser can
  // claim the full pane during a run. Below `lg` the two panes stack, so the
  // toggle only matters at the grid breakpoint.
  const [eventsCollapsed, setEventsCollapsed] = useState(false)

  // Wrap `runTask` so the task text is scanned before the SSE stream opens.
  const guardedRunTask = useCallback(async () => {
    const decision = await dlpScan(taskInput)
    if (decision === null) return // blocked / cancelled — keep input intact
    await runTask({ dlpConfirmed: decision.confirmed })
  }, [dlpScan, runTask, taskInput])

  // Unified status vocabulary: warning / accent / success / error /
  // foreground-secondary (canonical tokens, no bespoke warn/ok/err/fg-3).
  const STATUS_META = {
    idle:       { label: null },
    pending:    { label: t('status.starting'),   cls: 'bg-warning/15 text-warning border-warning/30' },
    running:    { label: t('status.running'),    cls: 'bg-accent/15 text-accent border-accent/30' },
    completed:  { label: t('status.completed'),  cls: 'bg-success/15 text-success border-success/30', Icon: CheckCircle2 },
    error:      { label: t('status.error'),      cls: 'bg-error/15 text-error border-error/30',       Icon: XCircle },
    stopped:    { label: t('status.stopped'),    cls: 'bg-foreground-secondary/15 text-foreground-secondary border-foreground-secondary/30',    Icon: StopCircle },
    timed_out:  { label: t('status.timedOut'),   cls: 'bg-warning/15 text-warning border-warning/30', Icon: AlertCircle },
  }

  const statusMeta = STATUS_META[status] || STATUS_META.idle

  return (
    <div className="h-full flex">
      {/* History sidebar — hidden on mobile */}
      <div className="hidden md:flex flex-col w-[280px] shrink-0">
        <TaskHistorySidebar
          tasks={taskHistory}
          currentTask={currentTask}
          onNewTask={newTask}
          onLoadTask={loadTask}
          onDeleteTask={deleteTask}
        />
      </div>

      {/* Page identity + live status portal into the single global top bar — no
          second glass header band stacked beneath it. */}
      <HeaderSlot side="start">
        <div className="flex min-w-0 items-center gap-2">
          <IconTile icon={Bot} tone="amber" size="sm" />
          <span className="truncate text-sm font-semibold text-foreground">{t('page.title')}</span>
          {statusMeta.label && (
            <Badge variant="outline" className={cn('text-xs capitalize', statusMeta.cls)}>
              {statusMeta.Icon && <statusMeta.Icon className="h-3 w-3 me-1" />}
              {statusMeta.label}
            </Badge>
          )}
        </div>
      </HeaderSlot>
      <HeaderSlot side="end">
        <div className="flex items-center gap-2">
          <PrivacyBadge mode="cloud" />
          {/* Mobile entry point to task history (desktop has the rail). */}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setHistoryOpen(true)}
            className="md:hidden shrink-0"
            aria-label={t('sidebar.title')}
            title={t('sidebar.title')}
          >
            <History className="h-5 w-5" />
          </Button>
        </div>
      </HeaderSlot>

      {/* Main column */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <div className="shrink-0 px-4 pt-2">
          <PrivacyBanner mode="cloud" />
        </div>
        {/* Task input bar */}
        <TaskInput
          taskInput={taskInput}
          setTaskInput={setTaskInput}
          selectedModel={selectedModel}
          setSelectedModel={setSelectedModel}
          status={status}
          onRun={guardedRunTask}
          onStop={stopTask}
        />

        {/* Error banner */}
        {error && status === 'error' && (
          <div className="flex-shrink-0 mx-4 mt-3 p-3 rounded-lg bg-error/10 border border-error/30 text-sm text-error flex items-center gap-2">
            <XCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Two-pane master-detail: live browser fills the inline-start track,
            the event stream rail sits inline-end. Tracks (not flex order) keep
            the layout writing-mode neutral, so RTL mirrors automatically.
            Stacks below `lg`; the events rail collapses to reclaim the pane. */}
        <div
          className={cn(
            'flex-1 min-h-0 overflow-y-auto p-4 grid gap-4 items-start',
            'grid-cols-1',
            eventsCollapsed
              ? 'lg:grid-cols-1'
              : 'lg:grid-cols-[minmax(0,1fr)_clamp(360px,30vw,460px)]'
          )}
        >
          {/* Browser pane */}
          <div className="min-w-0 flex flex-col gap-3">
            <div className="flex items-center justify-end">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setEventsCollapsed((v) => !v)}
                className="hidden lg:inline-flex shrink-0"
                aria-label={eventsCollapsed ? tc('actions.expand') : tc('actions.collapse')}
                title={eventsCollapsed ? tc('actions.expand') : tc('actions.collapse')}
              >
                {eventsCollapsed
                  ? <PanelRightOpen className="h-5 w-5 rtl:-scale-x-100" />
                  : <PanelRightClose className="h-5 w-5 rtl:-scale-x-100" />}
              </Button>
            </div>
            <LiveBrowserFrame liveUrl={liveUrl} status={status} />
          </div>

          {/* Event stream rail (inline-end). Hidden when collapsed on wide
              screens; always shown when stacked below `lg`. */}
          <div className={cn('min-w-0', eventsCollapsed && 'lg:hidden')}>
            <EventStream messages={messages} status={status} currentTask={currentTask} />
          </div>
        </div>
      </div>

      {/* Mobile task-history Sheet — same content as the desktop rail. */}
      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent side="start" className="p-0 w-[85vw] sm:max-w-sm">
          <SheetTitle className="sr-only">{t('sidebar.title')}</SheetTitle>
          <TaskHistorySidebar
            tasks={taskHistory}
            currentTask={currentTask}
            onNewTask={() => { newTask(); setHistoryOpen(false) }}
            onLoadTask={(id) => { loadTask(id); setHistoryOpen(false) }}
            onDeleteTask={deleteTask}
          />
        </SheetContent>
      </Sheet>

      {/* DLP violation modal */}
      {dlpModal}
      {/* Budget/credit exceeded modal */}
      {budgetModal}
    </div>
  )
}

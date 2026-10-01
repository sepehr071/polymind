import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  ChevronDown, Plus, Pencil, Trash2, ImageIcon, Check, Bot,
} from 'lucide-react'
import { imageService } from '../../services/imageService'
import { useConfirmDelete } from '../../hooks/useConfirmDelete'
import { prettifyModelName, friendlyModelLabel } from '@/utils/modelName'
import { cn } from '../../utils/cn'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { IconTile } from '@/components/ui/icon-tile'
import { Skeleton } from '@/components/ui/skeleton'
import ResponsivePicker from './ResponsivePicker'
import toast from 'react-hot-toast'

const THREADS_KEY = ['imageThreads']

/**
 * The Generate-tab header: the active session's title + a chevron that opens an
 * adaptive picker (Popover ≥md / bottom Sheet <md) of recent sessions (cover
 * thumb + title) with "+ New image" pinned on top and per-session rename /
 * delete (inline icon buttons revealed on hover, always shown on touch). Plus an
 * assistant pill that opens a second picker to bind / unbind an image assistant.
 *
 * Rename / delete reuse the same imageService calls + cache invalidation that
 * lived in ImageThread; the hook owns the active session, this just drives it.
 *
 * @param {object} props
 * @param {Array} props.threads               Recent sessions (cover_thumb + title).
 * @param {boolean} props.threadsLoading
 * @param {string|null} props.activeId
 * @param {object|null} props.activeThread    The loaded active thread (for its title).
 * @param {(id:string)=>void} props.onSelect
 * @param {()=>void} props.onNew
 * @param {string|null} props.assistantName   Bound image assistant name (pill label).
 * @param {Array} props.imageAssistants       Image-kind LLMConfigs to bind from.
 * @param {boolean} props.assistantsLoading
 * @param {string|null} props.assistantId      Currently bound assistant id (null = any model).
 * @param {(id:string|null)=>void} props.onBindAssistant  Bind (id) / unbind (null).
 */
export default function SessionSwitcher({
  threads,
  threadsLoading,
  activeId,
  activeThread,
  onSelect,
  onNew,
  assistantName = null,
  imageAssistants = [],
  assistantsLoading = false,
  assistantId = null,
  onBindAssistant,
}) {
  const { t } = useTranslation('dashboard')
  const queryClient = useQueryClient()
  const { confirm, confirmDialog } = useConfirmDelete()

  const [open, setOpen] = useState(false)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')

  // The current session title for the trigger. Prefer the loaded thread's title;
  // fall back to the list entry, then to a "New image" label for an unsaved one.
  const activeListEntry = threads.find((th) => th._id === activeId)
  const currentTitle =
    activeThread?.title ||
    activeListEntry?.title ||
    (activeId ? t('imageStudio.untitledThread') : t('imageStudio.newImage'))

  const submitRename = async (id) => {
    const title = renameValue.trim()
    setRenamingId(null)
    try {
      await imageService.renameThread(id, title)
      queryClient.invalidateQueries({ queryKey: THREADS_KEY })
      if (id === activeId) queryClient.invalidateQueries({ queryKey: ['imageThread', id] })
    } catch {
      toast.error(t('imageStudio.threadRenameFailed'))
    }
  }

  const handleDelete = async (th) => {
    const ok = await confirm({
      title: t('imageStudio.deleteThreadConfirm.title'),
      description: t('imageStudio.deleteThreadConfirm.message'),
      confirmLabel: t('imageStudio.deleteThreadConfirm.confirm'),
      cancelLabel: t('imageStudio.deleteThreadConfirm.cancel'),
      destructive: true,
    })
    if (!ok) return
    try {
      await imageService.deleteThread(th._id)
      queryClient.invalidateQueries({ queryKey: THREADS_KEY })
      queryClient.invalidateQueries({ queryKey: ['imageHistory'] })
      if (th._id === activeId) onNew()
      toast.success(t('imageStudio.threadDeleted'))
    } catch {
      toast.error(t('imageStudio.threadDeleteFailed'))
    }
  }

  const bindAssistant = (id) => {
    setAssistantOpen(false)
    onBindAssistant?.(id)
  }

  // The bound assistant (from the pickable list) — used to show its avatar on the
  // pill so a bound assistant reads as more than a generic Bot chip.
  const boundAssistant = assistantId
    ? imageAssistants.find((c) => (c._id || c.id) === assistantId)
    : null
  const boundEmoji = boundAssistant?.avatar?.type === 'emoji' ? boundAssistant.avatar.value : null

  return (
    <div className="flex items-center gap-2 min-w-0">
      {/* SESSION switcher — Popover ≥md, bottom Sheet <md. */}
      <ResponsivePicker
        open={open}
        onOpenChange={setOpen}
        align="start"
        title={t('imageStudio.recentSessions')}
        contentClassName="w-72 max-w-[90vw]"
        trigger={
          <button
            type="button"
            className={cn(
              'group flex items-center gap-1.5 min-w-0 rounded-lg px-2 py-1 -ms-2',
              'text-foreground hover:bg-background-tertiary transition-colors',
            )}
          >
            <span className="truncate text-lg font-semibold">{currentTitle}</span>
            <ChevronDown className="h-4 w-4 shrink-0 text-foreground-tertiary group-hover:text-foreground transition-colors" />
          </button>
        }
      >
        <div className="space-y-1">
          {/* + New image — pinned on top */}
          <button
            type="button"
            onClick={() => { setOpen(false); onNew() }}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm font-medium text-foreground hover:bg-background-tertiary transition-colors"
          >
            <Plus className="h-4 w-4" />
            <span>{t('imageStudio.newImage')}</span>
          </button>

          <div className="my-1 h-px bg-border" />

          <div className="px-2 py-1 text-xs text-foreground-tertiary">
            {t('imageStudio.recentSessions')}
          </div>

          {threadsLoading ? (
            <div className="space-y-1.5 p-1.5">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 w-full rounded-lg" />)}
            </div>
          ) : threads.length === 0 ? (
            <p className="px-2 py-3 text-xs text-foreground-tertiary">{t('imageStudio.noThreadsYet')}</p>
          ) : (
            threads.map((th) => (
              <div
                key={th._id}
                className={cn(
                  'group flex items-center gap-2 rounded-lg p-1.5 cursor-pointer transition-colors',
                  th._id === activeId ? 'bg-accent/10' : 'hover:bg-background-tertiary',
                )}
                onClick={() => {
                  if (renamingId === th._id) return
                  if (th._id !== activeId) onSelect(th._id)
                  setOpen(false)
                }}
              >
                {th.cover_thumb ? (
                  <div className="h-9 w-9 shrink-0 rounded-xl bg-background-tertiary overflow-hidden flex items-center justify-center">
                    <img src={th.cover_thumb} alt="" className="h-full w-full object-cover" />
                  </div>
                ) : (
                  <IconTile icon={ImageIcon} tone="amber" size="lg" />
                )}

                {renamingId === th._id ? (
                  <Input
                    autoFocus
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onBlur={() => submitRename(th._id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') submitRename(th._id)
                      if (e.key === 'Escape') setRenamingId(null)
                    }}
                    onClick={(e) => e.stopPropagation()}
                    className="h-7 flex-1 min-w-0"
                  />
                ) : (
                  <span className="flex-1 min-w-0 truncate text-sm text-foreground">
                    {th.title || t('imageStudio.untitledThread')}
                  </span>
                )}

                {th._id === activeId && renamingId !== th._id && (
                  <Check className="h-4 w-4 shrink-0 text-accent" />
                )}

                {/* Inline rename / delete — revealed on hover/focus, always shown
                    on touch (no nested dropdown). stopPropagation so the row isn't
                    selected when acting on a session. */}
                {renamingId !== th._id && (
                  <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 pointer-coarse:opacity-100 transition-opacity">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        setRenamingId(th._id)
                        setRenameValue(th.title || '')
                      }}
                      aria-label={t('imageStudio.rename')}
                      title={t('imageStudio.rename')}
                      className="flex h-7 w-7 items-center justify-center rounded-md text-foreground-tertiary hover:bg-background-secondary hover:text-foreground transition-colors"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); handleDelete(th) }}
                      aria-label={t('imageStudio.deleteThread')}
                      title={t('imageStudio.deleteThread')}
                      className="flex h-7 w-7 items-center justify-center rounded-md text-foreground-tertiary hover:bg-destructive/10 hover:text-destructive transition-colors"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </ResponsivePicker>

      {/* Bold New-Image CTA — the dropdown's pinned row stays as a fallback, but
          starting a fresh image deserves a first-class button. Icon-only below
          sm so the header row doesn't crowd on phones. */}
      <Button
        size="sm"
        onClick={onNew}
        aria-label={t('imageStudio.newImage')}
        className="h-8 shrink-0 gap-1.5 rounded-full px-3 sm:px-3.5 font-semibold"
      >
        <Plus className="h-4 w-4" />
        <span className="hidden sm:inline">{t('imageStudio.newImage')}</span>
      </Button>

      {/* ASSISTANT binding — pill shows the bound name or a generic label; the
          picker lets the user pick an image assistant or "Use any model". */}
      <ResponsivePicker
        open={assistantOpen}
        onOpenChange={setAssistantOpen}
        align="start"
        title={t('imageStudio.chooseAssistant')}
        contentClassName="w-72 max-w-[90vw]"
        trigger={
          <button
            type="button"
            className={cn(
              'inline-flex items-center gap-1.5 shrink-0 rounded-full px-3 py-1 text-xs transition-colors',
              assistantId
                ? 'bg-accent/10 text-accent hover:bg-accent/15'
                : 'bg-background-tertiary text-foreground-secondary hover:text-foreground',
            )}
          >
            {boundEmoji ? (
              <span className="text-sm leading-none" aria-hidden="true">{boundEmoji}</span>
            ) : (
              <Bot className="h-3.5 w-3.5" />
            )}
            <span className="truncate max-w-[140px]">
              {assistantId ? (assistantName || t('imageStudio.assistant')) : t('imageStudio.assistant')}
            </span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-70" />
          </button>
        }
      >
        <div className="space-y-1">
          {/* Use any model — unbind. */}
          <button
            type="button"
            onClick={() => bindAssistant(null)}
            className="flex w-full items-center gap-2 rounded-lg p-1.5 text-start hover:bg-background-tertiary transition-colors"
          >
            <IconTile icon={Bot} tone="neutral" size="lg" />
            <span className="flex-1 min-w-0 truncate text-sm text-foreground">
              {t('imageStudio.useAnyModel')}
            </span>
            {!assistantId && <Check className="h-4 w-4 shrink-0 text-accent" />}
          </button>

          <div className="my-1 h-px bg-border" />

          {assistantsLoading ? (
            <div className="space-y-1.5 p-1.5">
              {[0, 1].map((i) => <Skeleton key={i} className="h-11 w-full rounded-lg" />)}
            </div>
          ) : imageAssistants.length === 0 ? (
            <div className="px-2 py-3 space-y-2">
              <p className="text-xs text-foreground-tertiary">
                {t('imageStudio.noImageAssistants')}
              </p>
              <Link
                to="/configs"
                onClick={() => setAssistantOpen(false)}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline"
              >
                <Bot className="h-3.5 w-3.5" />
                {t('imageStudio.manageAssistants')}
              </Link>
            </div>
          ) : (
            imageAssistants.map((cfg) => {
              const id = cfg._id || cfg.id
              const selected = id === assistantId
              const modelLine = friendlyModelLabel(cfg.model_name) || prettifyModelName(cfg.model_id)
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => bindAssistant(id)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-lg p-1.5 text-start transition-colors',
                    selected ? 'bg-accent/10' : 'hover:bg-background-tertiary',
                  )}
                >
                  {cfg.avatar?.type === 'emoji' ? (
                    <div className="h-9 w-9 shrink-0 rounded-xl bg-accent/10 flex items-center justify-center text-base text-accent overflow-hidden">
                      {cfg.avatar.value}
                    </div>
                  ) : (
                    <IconTile icon={ImageIcon} tone="amber" size="lg" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-sm text-foreground">{cfg.name}</p>
                    {modelLine && (
                      <p className="truncate text-xs text-foreground-tertiary" dir="ltr">{modelLine}</p>
                    )}
                  </div>
                  {selected && <Check className="h-4 w-4 shrink-0 text-accent" />}
                </button>
              )
            })
          )}
        </div>
      </ResponsivePicker>

      {confirmDialog}
    </div>
  )
}

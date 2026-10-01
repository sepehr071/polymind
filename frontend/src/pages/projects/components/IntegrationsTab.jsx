import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  Link as LinkIcon,
  Plus,
  Copy,
  RefreshCw,
  Trash2,
  MoreHorizontal,
  AlertTriangle,
  Webhook,
} from 'lucide-react'
import Section from '@/components/teams/Section'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { Checkbox } from '@/components/ui/checkbox'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'
import projectService from '@/services/projectService'

const EVENT_OPTIONS = [
  { value: 'chat.completed', labelKey: 'projectSettings.integrations.eventChatCompleted' },
  { value: 'chat.message_sent', labelKey: 'projectSettings.integrations.eventChatMessageSent' },
  { value: 'image.generated', labelKey: 'projectSettings.integrations.eventImageGenerated' },
  { value: 'workflow.run_completed', labelKey: 'projectSettings.integrations.eventWorkflowRunCompleted' },
  { value: '*', labelKey: 'projectSettings.integrations.eventAll' },
]

function copyToClipboard(text) {
  if (!text) return Promise.resolve(false)
  return navigator.clipboard
    .writeText(text)
    .then(() => true)
    .catch(() => false)
}

export default function IntegrationsTab({ project }) {
  const { t } = useTranslation('projects')
  const { confirm, confirmDialog } = useConfirmDelete()
  const pid = project?._id
  const isOwner = project?.member_role === 'owner'

  const [webhooks, setWebhooks] = useState([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [secretReveal, setSecretReveal] = useState(null) // {webhook, secret}

  const load = useCallback(async () => {
    if (!pid) return
    setLoading(true)
    try {
      const data = await projectService.getWebhooks(pid)
      const list = Array.isArray(data) ? data : data?.webhooks || []
      setWebhooks(list)
    } catch (err) {
      const status = err.response?.status
      if (status === 403) {
        toast.error(t('projectSettings.integrations.toasts.viewForbidden'))
      } else {
        toast.error(t('projectSettings.integrations.toasts.loadFailed'))
      }
    } finally {
      setLoading(false)
    }
  }, [pid, t])

  useEffect(() => {
    load()
  }, [load])

  async function handleCreate(payload) {
    const created = await projectService.createWebhook(pid, payload)
    await load()
    if (created?.secret) {
      setSecretReveal({
        webhook: created,
        secret: created.secret,
        title: t('projectSettings.integrations.dialog.createdTitle'),
      })
    }
    return created
  }

  async function handleToggleEnabled(wh) {
    if (!isOwner) return
    const next = !wh.enabled
    setWebhooks((prev) =>
      prev.map((w) => (w._id === wh._id ? { ...w, enabled: next } : w)),
    )
    try {
      await projectService.updateWebhook(pid, wh._id, { enabled: next })
      toast.success(next ? t('projectSettings.integrations.toasts.enabled') : t('projectSettings.integrations.toasts.disabled'))
    } catch (err) {
      // revert
      setWebhooks((prev) =>
        prev.map((w) => (w._id === wh._id ? { ...w, enabled: !next } : w)),
      )
      toast.error(err.response?.data?.error || t('projectSettings.integrations.toasts.updateFailed'))
    }
  }

  async function handleDelete(wh) {
    if (!isOwner) return
    const ok = await confirm({
      title: t('projectSettings.integrations.confirm.deleteTitle'),
      description: t('projectSettings.integrations.confirm.delete', { name: wh.name || wh.url }),
      confirmLabel: t('common:actions.delete'),
      destructive: true,
    })
    if (!ok) return
    try {
      await projectService.deleteWebhook(pid, wh._id)
      toast.success(t('projectSettings.integrations.toasts.deleted'))
      await load()
    } catch (err) {
      toast.error(err.response?.data?.error || t('projectSettings.integrations.toasts.deleteFailed'))
    }
  }

  async function handleRotateSecret(wh) {
    if (!isOwner) return
    const ok = await confirm({
      title: t('projectSettings.integrations.confirm.rotateTitle'),
      description: t('projectSettings.integrations.confirm.rotate'),
      confirmLabel: t('projectSettings.integrations.rotateSecret'),
      destructive: true,
    })
    if (!ok) return
    try {
      const data = await projectService.rotateWebhookSecret(pid, wh._id)
      if (data?.secret) {
        setSecretReveal({
          webhook: wh,
          secret: data.secret,
          title: t('projectSettings.integrations.dialog.rotatedTitle'),
        })
      }
      toast.success(t('projectSettings.integrations.toasts.secretRotated'))
    } catch (err) {
      toast.error(err.response?.data?.error || t('projectSettings.integrations.toasts.rotateFailed'))
    }
  }

  return (
    <div className="space-y-4">
      <Section
        title={t('projectSettings.integrations.webhooksTitle')}
        hint={t('projectSettings.integrations.webhooksHint')}
        action={
          isOwner && (
            <Button
              size="sm"
              onClick={() => setCreateOpen(true)}
              className="gap-1.5"
            >
              <Plus className="h-3.5 w-3.5" />
              {t('projectSettings.integrations.addWebhook')}
            </Button>
          )
        }
      >
        {loading ? (
          <div className="px-2 py-6 text-sm text-fg-3">{t('projectSettings.integrations.loading')}</div>
        ) : webhooks.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
            <Webhook className="h-6 w-6 text-fg-3" />
            <p className="text-sm text-fg-2">{t('projectSettings.integrations.empty.title')}</p>
            <p className="text-xs text-fg-3 max-w-md">
              {isOwner
                ? t('projectSettings.integrations.empty.ownerHint')
                : t('projectSettings.integrations.empty.viewerHint')}
            </p>
          </div>
        ) : (
          <ul className="flex flex-col">
            {webhooks.map((wh) => (
              <li
                key={wh._id}
                className="flex items-center gap-3 py-3 border-b border-line last:border-0"
              >
                <div className="flex flex-col min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-fg-1 truncate">
                      {wh.name || t('projectSettings.integrations.unnamedWebhook')}
                    </span>
                    {!wh.enabled && (
                      <span className="inline-flex items-center rounded-full border border-line bg-bg-3 px-2 py-0.5 text-[10px] font-medium text-fg-2">
                        {t('status.disabled')}
                      </span>
                    )}
                  </div>
                  <code dir="ltr" className="mt-0.5 truncate font-mono text-[11px] text-fg-3 max-w-full">
                    {wh.url}
                  </code>
                  {Array.isArray(wh.events) && wh.events.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {wh.events.map((ev) => (
                        <span
                          key={ev}
                          className="inline-flex items-center rounded-full border border-line bg-bg-2/50 px-1.5 py-0.5 text-[10px] font-mono text-fg-2"
                        >
                          {ev}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <Switch
                  checked={!!wh.enabled}
                  onCheckedChange={() => handleToggleEnabled(wh)}
                  disabled={!isOwner}
                />
                {isOwner && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={t('projectSettings.integrations.actionsAriaLabel')}
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => handleRotateSecret(wh)}>
                        <RefreshCw className="h-4 w-4" />
                        {t('projectSettings.integrations.rotateSecret')}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onClick={() => handleDelete(wh)}
                        className="text-err focus:text-err"
                      >
                        <Trash2 className="h-4 w-4" />
                        {t('common:actions.delete')}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <CreateWebhookDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSubmit={handleCreate}
      />

      <SecretRevealDialog
        open={!!secretReveal}
        onOpenChange={(v) => !v && setSecretReveal(null)}
        secret={secretReveal?.secret}
        webhook={secretReveal?.webhook}
        title={secretReveal?.title}
      />

      {confirmDialog}
    </div>
  )
}

function CreateWebhookDialog({ open, onOpenChange, onSubmit }) {
  const { t } = useTranslation('projects')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [events, setEvents] = useState([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (open) {
      setName('')
      setUrl('')
      setEvents([])
      setErr(null)
    }
  }, [open])

  function toggleEvent(value) {
    setEvents((prev) =>
      prev.includes(value)
        ? prev.filter((v) => v !== value)
        : [...prev, value],
    )
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      const payload = {
        name: name.trim() || t('projectSettings.integrations.untitledWebhook'),
        url: url.trim(),
      }
      if (events.length > 0) payload.events = events
      await onSubmit(payload)
      onOpenChange(false)
    } catch (ex) {
      setErr(
        ex?.response?.data?.error ||
          ex?.message ||
          t('projectSettings.integrations.toasts.createFailed'),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('projectSettings.integrations.addWebhook')}</DialogTitle>
          <DialogDescription>
            {t('projectSettings.integrations.addDialogDescription')}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="wh-name">{t('projectSettings.integrations.webhookNameLabel')}</Label>
            <Input
              id="wh-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('projectSettings.integrations.webhookNamePlaceholder')}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="wh-url">{t('projectSettings.integrations.webhookUrlLabel')}</Label>
            <Input
              id="wh-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('projectSettings.integrations.webhookUrlPlaceholder')}
              dir="ltr"
              required
            />
          </div>

          <div className="space-y-2">
            <Label>{t('projectSettings.integrations.webhookEventsLabel')}</Label>
            <div className="flex flex-col gap-2 rounded-xl border border-line bg-bg-2/50 p-3">
              {EVENT_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className="flex items-center gap-2 cursor-pointer"
                >
                  <Checkbox
                    checked={events.includes(opt.value)}
                    onCheckedChange={() => toggleEvent(opt.value)}
                  />
                  <span className="font-mono text-xs text-fg-1">
                    {t(opt.labelKey)}
                  </span>
                </label>
              ))}
            </div>
            <p className="text-[11px] text-fg-3">
              {t('projectSettings.integrations.eventsEmptyHint')}
            </p>
          </div>

          {err && <p className="text-sm text-err">{err}</p>}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              {t('common:actions.cancel')}
            </Button>
            <Button type="submit" disabled={busy || !url.trim()}>
              {busy ? '...' : t('projectSettings.integrations.saveWebhook')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function SecretRevealDialog({ open, onOpenChange, secret, webhook, title }) {
  const { t } = useTranslation('projects')
  const [revealed, setRevealed] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (open) {
      setRevealed(false)
      setCopied(false)
    }
  }, [open])

  if (!secret) return null

  async function handleCopy() {
    const ok = await copyToClipboard(secret)
    if (ok) {
      setCopied(true)
      toast.success(t('projectSettings.integrations.toasts.secretCopied'))
      setTimeout(() => setCopied(false), 2000)
    } else {
      toast.error(t('projectSettings.integrations.toasts.copyFailed'))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <LinkIcon className="h-4 w-4 text-accent" />
            {title || t('projectSettings.integrations.dialog.secretFallbackTitle')}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="rounded-md border border-warn/30 bg-warn/10 p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 flex-shrink-0 text-warn mt-0.5" />
              <div>
                <p className="text-sm font-medium text-warn">
                  {t('projectSettings.integrations.dialog.warningTitle')}
                </p>
                <p className="mt-0.5 text-xs text-warn/80">
                  {t('projectSettings.integrations.dialog.warningBody')}
                </p>
              </div>
            </div>
          </div>

          {webhook && (
            <p className="text-xs text-fg-3">
              {t('projectSettings.integrations.dialog.webhookLabel')} <span dir="ltr" className="text-fg-1">{webhook.name || webhook.url}</span>
            </p>
          )}

          <div className="flex flex-col gap-2">
            <Label>{t('projectSettings.integrations.dialog.signingSecretLabel')}</Label>
            <div className="flex items-stretch gap-2">
              <code
                dir="ltr"
                className="flex-1 select-all rounded-md border border-line bg-bg-2 px-3 py-2 font-mono text-xs text-fg-1 break-all"
                style={
                  !revealed
                    ? { filter: 'blur(6px)', userSelect: 'none' }
                    : undefined
                }
              >
                {secret}
              </code>
              <div className="flex flex-col gap-1.5">
                {!revealed ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setRevealed(true)}
                  >
                    {t('projectSettings.integrations.dialog.reveal')}
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    onClick={handleCopy}
                    className="gap-1.5"
                  >
                    <Copy className="h-3.5 w-3.5" />
                    {copied ? t('common:actions.copied') : t('common:actions.copy')}
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>{t('projectSettings.integrations.dialog.done')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'

export default function DangerZone({
  title,
  description,
  confirmText,
  disabled,
  disabledReason,
  onConfirm,
}) {
  const { t } = useTranslation('projects')
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [loading, setLoading] = useState(false)

  const canConfirm = typed === confirmText

  async function handleConfirm() {
    if (!canConfirm) return
    setLoading(true)
    try {
      await onConfirm()
      setOpen(false)
    } finally {
      setLoading(false)
      setTyped('')
    }
  }

  function handleOpen() {
    if (disabled) return
    setTyped('')
    setOpen(true)
  }

  return (
    <div className="rounded-2xl border border-error/30 bg-error/10 p-5">
      <div className="flex items-start gap-3">
        <AlertTriangle className="h-5 w-5 text-error mt-0.5 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-error">{title}</h3>
          <p className="mt-1 text-sm text-foreground-secondary">{description}</p>
          {disabled && disabledReason && (
            <p className="mt-2 text-xs text-foreground-tertiary italic">{disabledReason}</p>
          )}
        </div>
        <Button
          variant="destructive"
          size="sm"
          onClick={handleOpen}
          disabled={disabled}
          className="flex-shrink-0"
        >
          {title}
        </Button>
      </div>

      <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) setTyped('') }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="text-error">{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <Label className="text-sm text-foreground-secondary">
              {t('workspaceSettings.danger.typeToConfirm', { name: confirmText })}
            </Label>
            <Input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={confirmText}
              autoFocus
              onKeyDown={(e) => { if (e.key === 'Enter' && canConfirm) handleConfirm() }}
            />
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={loading}>
              {t('workspaceSettings.danger.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleConfirm}
              disabled={!canConfirm || loading}
            >
              {loading ? t('workspaceSettings.danger.deleting') : t('workspaceSettings.danger.confirmDelete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

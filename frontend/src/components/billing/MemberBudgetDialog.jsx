import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Wallet } from 'lucide-react'
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

/**
 * MemberBudgetDialog — set (or clear) a member's monthly USD budget inside one
 * org. Empty input clears the budget (null). The caller owns the request via
 * `onConfirm(amountUsd|null)`; a thrown error is surfaced inline.
 *
 * @param {boolean} open
 * @param {() => void} onClose
 * @param {string} orgName
 * @param {string} [targetName]  Single member label.
 * @param {number} [bulkCount]   When >1, bulk copy is used.
 * @param {number|null} [initialAmount]
 * @param {(amountUsd: number|null) => Promise<void>} onConfirm
 */
export default function MemberBudgetDialog({
  open,
  onClose,
  orgName,
  targetName,
  bulkCount,
  initialAmount,
  onConfirm,
}) {
  const { t } = useTranslation('admin')
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const isBulk = Number(bulkCount) > 1

  useEffect(() => {
    if (open) {
      setAmount(initialAmount != null ? String(initialAmount) : '')
      setErr(null)
    }
  }, [open, initialAmount])

  const val = amount.trim() === '' ? null : Number(amount)
  const valid = val === null || (Number.isFinite(val) && val >= 0)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!valid) return
    setBusy(true)
    setErr(null)
    try {
      await onConfirm(val)
      onClose?.()
    } catch (ex) {
      setErr(
        ex?.response?.data?.error || ex?.message || t('users.budgetFailed'),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v && !busy) onClose?.()
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wallet className="h-5 w-5 text-accent" />
            {isBulk
              ? t('users.budgetDialog.bulkTitle', { count: Number(bulkCount) })
              : t('users.budgetDialog.title')}
          </DialogTitle>
          <DialogDescription>
            {isBulk
              ? t('users.budgetDialog.bulkSubtitle', { org: orgName })
              : t('users.budgetDialog.subtitle', { name: targetName || '—', org: orgName })}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="member-budget-amount">{t('users.budgetDialog.amountLabel')}</Label>
            <Input
              id="member-budget-amount"
              type="number"
              min="0"
              step="0.01"
              dir="ltr"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="50.00"
              autoFocus
            />
            <p className="text-xs text-fg-2">{t('users.budgetDialog.amountHint')}</p>
          </div>

          {err && <p className="text-sm text-err">{err}</p>}

          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => onClose?.()} disabled={busy}>
              {t('users.banModal.cancel')}
            </Button>
            <Button type="submit" disabled={busy || !valid}>
              {busy && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
              {busy ? t('users.budgetDialog.saving') : t('users.budgetDialog.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

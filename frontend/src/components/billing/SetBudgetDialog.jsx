import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Gauge, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { CostValue } from '@/components/ui/CostValue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'

/**
 * SetBudgetDialog — sets a monthly spend CEILING (a limit, not money). Distinct
 * from AddCreditsDialog: that records a prepaid ledger entry; this configures an
 * advisory-or-enforced budget cap. Reused for a team-wide budget and per-member
 * budgets (the caller drives `title`/`subtitle`/`currentAmount`/`enabled`).
 *
 * A single ceiling number input (LTR — it's a currency figure) plus an enable
 * toggle and an explicit "clear" action. Clearing removes the cap entirely,
 * surfaced to the caller as `amount_usd: null`.
 *
 * @param {object}        props
 * @param {boolean}       props.open
 * @param {() => void}    props.onClose             Closer (cancel + success).
 * @param {string}        props.title
 * @param {string}        [props.subtitle]
 * @param {number|null}   props.currentAmount       Existing ceiling, or null when unset.
 * @param {boolean}       [props.enabled]           Whether the cap is active.
 * @param {boolean}       [props.busy]              Caller-controlled in-flight state.
 * @param {(v: {amount_usd: number|null, enabled: boolean}) => (void|Promise<void>)} props.onConfirm
 *   `amount_usd: null` ⇒ clear the budget. The caller owns the PUT + toast +
 *   query-invalidation; this dialog just collects the value.
 */
export default function SetBudgetDialog({
  open,
  onClose,
  title,
  subtitle,
  currentAmount = null,
  enabled = true,
  busy = false,
  onConfirm,
}) {
  const { t } = useTranslation('billing')
  const [amount, setAmount] = useState('')
  const [isEnabled, setIsEnabled] = useState(true)

  // Seed the form from the current values each time the dialog opens.
  useEffect(() => {
    if (open) {
      setAmount(
        currentAmount != null && Number.isFinite(Number(currentAmount))
          ? String(currentAmount)
          : '',
      )
      setIsEnabled(enabled !== false)
    }
  }, [open, currentAmount, enabled])

  const val = Number(amount)
  const amountValid = amount !== '' && Number.isFinite(val) && val > 0
  const hasExistingBudget =
    currentAmount != null && Number.isFinite(Number(currentAmount))

  async function handleSave(e) {
    e.preventDefault()
    if (!amountValid || busy) return
    await onConfirm?.({ amount_usd: val, enabled: isEnabled })
  }

  async function handleClear() {
    if (busy) return
    await onConfirm?.({ amount_usd: null, enabled: false })
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
            <Gauge className="h-4 w-4 text-accent" aria-hidden="true" />
            {title}
          </DialogTitle>
          {subtitle && <DialogDescription>{subtitle}</DialogDescription>}
        </DialogHeader>

        <form onSubmit={handleSave} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="set-budget-amount">{t('setBudget.amountLabel')}</Label>
            <Input
              id="set-budget-amount"
              type="number"
              step="0.01"
              min="0"
              dir="ltr"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={t('setBudget.amountPlaceholder')}
              autoFocus
            />
            <p className="text-[11px] text-fg-3">{t('setBudget.amountHint')}</p>
          </div>

          <div className="flex items-center justify-between rounded-md border border-fg-3/30 bg-bg-2/40 p-3">
            <div className="space-y-0.5 pe-3">
              <Label htmlFor="set-budget-enabled" className="cursor-pointer">
                {t('setBudget.enabledLabel')}
              </Label>
              <p className="text-[11px] text-fg-3">{t('setBudget.enabledHint')}</p>
            </div>
            <Switch
              id="set-budget-enabled"
              checked={isEnabled}
              onCheckedChange={setIsEnabled}
              disabled={busy}
            />
          </div>

          {hasExistingBudget && (
            <div className="flex items-center justify-between rounded-md border border-fg-3/30 bg-bg-2/40 px-3 py-2 text-sm">
              <span className="text-fg-3">{t('setBudget.currentLabel')}</span>
              <CostValue usd={Number(currentAmount)} className="font-medium text-fg-1" />
            </div>
          )}

          <DialogFooter className="flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            {/* Clearing the cap is a left-aligned, low-emphasis escape hatch —
                only meaningful when a budget actually exists. */}
            {hasExistingBudget ? (
              <Button
                type="button"
                variant="ghost"
                onClick={handleClear}
                disabled={busy}
                className="text-err hover:text-err sm:me-auto"
              >
                <Trash2 className="me-2 h-4 w-4" aria-hidden="true" />
                {t('setBudget.clearButton')}
              </Button>
            ) : (
              <span className="hidden sm:block sm:me-auto" />
            )}
            <div className="flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() => onClose?.()}
                disabled={busy}
              >
                {t('setBudget.cancelButton')}
              </Button>
              <Button type="submit" disabled={busy || !amountValid}>
                {busy && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
                {busy ? t('setBudget.savingButton') : t('setBudget.saveButton')}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

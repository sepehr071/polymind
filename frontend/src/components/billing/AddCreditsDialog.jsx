import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, AlertTriangle, Wallet } from 'lucide-react'
import { fmtCurrency } from '@/utils/persianLocale'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { CostValue } from '@/components/ui/CostValue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

/**
 * AddCreditsDialog — the SINGLE manual-credit-entry dialog for every caller
 * (owner Billing tab, holding `/admin` companies, platform operator). It records
 * a ledger entry; no card is ever charged here. Two-step flow: enter
 * amount/type/note → review the delta + projected balance → confirm.
 *
 * The dialog OWNS the form + the review/confirm gate, but knows nothing about
 * which service to call: the caller passes `onConfirm({ amount, type, note })`
 * (an async fn that does the real POST + toast + query-invalidation) and the
 * dialog awaits it, surfacing any thrown error inline and keeping itself open.
 *
 * @param {object}   props
 * @param {boolean}  props.open
 * @param {() => void} props.onClose            Closer (called on cancel + success).
 * @param {'owner'|'company'|'holding'} [props.scope='owner']
 *   Drives only the copy (title / subtitle / target name). `owner` + `company`
 *   target a workspace; `holding` targets the org-level pool.
 * @param {string}   [props.targetName]         Workspace/company name (company scope).
 * @param {number|null} [props.currentBalance]  Known remaining balance — when set,
 *   the review step shows the projected new balance.
 * @param {(entry: {amount:number, type:string, note:string, source?:string}) => Promise<void>} props.onConfirm
 *   Performs the real charge. Throws to surface an inline error. `amount` is a
 *   parsed `number`; `note` is trimmed. `source` (`'holding'|'external'`) is only
 *   present for `company` scope — where the funds come from (transfer from the
 *   holding pool vs. a direct external top-up).
 */
export default function AddCreditsDialog({
  open,
  onClose,
  scope = 'owner',
  targetName,
  currentBalance,
  onConfirm,
}) {
  const { t } = useTranslation(['billing', 'common'])
  const [amount, setAmount] = useState('')
  const [type, setType] = useState('top_up')
  const [note, setNote] = useState('')
  // Company top-ups choose a funding source; defaults to the holding pool.
  const [source, setSource] = useState('holding')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [reviewing, setReviewing] = useState(false)

  const showSource = scope === 'company'

  useEffect(() => {
    if (open) {
      setAmount('')
      setType('top_up')
      setNote('')
      setSource('holding')
      setErr(null)
      setReviewing(false)
    }
  }, [open])

  // Editing the amount/type after reaching the review step invalidates it.
  useEffect(() => {
    setReviewing(false)
  }, [amount, type])

  const val = Number(amount)
  const amountValid = amount !== '' && Number.isFinite(val) && val !== 0
  const isNegative = amountValid && val < 0
  // Negative amounts only make sense as an explicit "adjustment" debit.
  const negativeBlocked = isNegative && type !== 'adjustment'
  const knownBalance = currentBalance != null && Number.isFinite(Number(currentBalance))
  const projectedBalance = knownBalance ? Number(currentBalance) + val : null

  const resolvedTargetName = useMemo(() => {
    if (scope === 'holding') return t('addCredits.holdingTargetName')
    return targetName || '—'
  }, [scope, targetName, t])

  const title =
    scope === 'holding'
      ? t('addCredits.holdingTitle')
      : scope === 'company'
        ? t('addCredits.companyTitle')
        : t('addCredits.ownerTitle')
  const subtitle =
    scope === 'holding'
      ? t('addCredits.holdingSubtitle')
      : scope === 'company'
        ? t('addCredits.companySubtitle', { name: resolvedTargetName })
        : t('addCredits.ownerSubtitle')

  async function handleSubmit(e) {
    e.preventDefault()
    if (!amountValid || negativeBlocked) return
    // First submit shows the review step (delta + projected balance); only the
    // second click actually records the ledger entry — money never moves on a
    // single click.
    if (!reviewing) {
      setReviewing(true)
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await onConfirm({
        amount: val,
        type,
        note: note.trim(),
        ...(showSource ? { source } : {}),
      })
      onClose?.()
    } catch (ex) {
      setErr(
        ex?.response?.data?.error || ex?.message || t('addCredits.errorFailed'),
      )
      setReviewing(false)
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
            {title}
          </DialogTitle>
          <DialogDescription>{subtitle}</DialogDescription>
        </DialogHeader>

        {/* Prepaid honesty: no card is charged — this records a ledger entry. */}
        <p className="-mt-1 text-[13px] font-medium leading-snug text-fg-2">
          {t('addCredits.lead')}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="add-credit-amount">{t('addCredits.amountLabel')}</Label>
            <Input
              id="add-credit-amount"
              type="number"
              step="0.01"
              dir="ltr"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={t('addCredits.amountPlaceholder')}
              autoFocus
              required
            />
            <p className="text-xs text-fg-2">{t('addCredits.amountHint')}</p>
            {negativeBlocked && (
              <p className="text-[11px] text-warn">
                {t('addCredits.negativeBlockedHint')}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="add-credit-type">{t('addCredits.typeLabel')}</Label>
            <Select value={type} onValueChange={setType}>
              <SelectTrigger id="add-credit-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="top_up">{t('addCredits.typeTopUp')}</SelectItem>
                <SelectItem value="adjustment">
                  {t('addCredits.typeAdjustment')}
                </SelectItem>
                <SelectItem value="refund">{t('addCredits.typeRefund')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {showSource && (
            <div className="space-y-2">
              <Label htmlFor="add-credit-source">{t('addCredits.sourceLabel')}</Label>
              <Select value={source} onValueChange={setSource}>
                <SelectTrigger id="add-credit-source">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="holding">
                    {t('addCredits.sourceHolding')}
                  </SelectItem>
                  <SelectItem value="external">
                    {t('addCredits.sourceExternal')}
                  </SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-fg-2">
                {source === 'holding'
                  ? t('addCredits.sourceHoldingHint')
                  : t('addCredits.sourceExternalHint')}
              </p>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="add-credit-note">{t('addCredits.noteLabel')}</Label>
            <Textarea
              id="add-credit-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={500}
              rows={2}
              placeholder={t('addCredits.notePlaceholder')}
            />
          </div>

          {reviewing && (
            <div className="space-y-1.5 rounded-md border border-line bg-bg-2/70 p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-fg-2">{t('addCredits.changeLabel')}</span>
                <span
                  className={isNegative ? 'font-medium text-err' : 'font-medium text-ok'}
                  dir="ltr"
                >
                  {val >= 0 ? '+' : '−'}
                  {fmtCurrency(Math.abs(val))}
                </span>
              </div>
              {knownBalance && (
                <>
                  <div className="flex items-center justify-between">
                    <span className="text-fg-2">
                      {t('addCredits.currentBalance')}
                    </span>
                    <CostValue usd={Number(currentBalance)} className="text-fg-1" />
                  </div>
                  <div className="flex items-center justify-between border-t border-line pt-1.5">
                    <span className="text-fg-2">{t('addCredits.newBalance')}</span>
                    <CostValue
                      usd={projectedBalance}
                      className="font-semibold text-fg-0"
                    />
                  </div>
                </>
              )}
              {isNegative && (
                <p className="flex items-start gap-1.5 pt-1 text-[11px] text-warn">
                  <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
                  {t('addCredits.negativeWarn')}
                </p>
              )}
            </div>
          )}

          {err && <p className="text-sm text-err">{err}</p>}

          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => (reviewing ? setReviewing(false) : onClose?.())}
              disabled={busy}
            >
              {reviewing ? t('common:actions.back') : t('common:actions.cancel')}
            </Button>
            <Button type="submit" disabled={busy || !amountValid || negativeBlocked}>
              {busy && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
              {busy
                ? t('addCredits.recording')
                : reviewing
                  ? t('addCredits.confirmButton')
                  : t('addCredits.reviewButton')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

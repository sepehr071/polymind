import { useTranslation } from 'react-i18next'
import { Ban } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CostValue } from '@/components/ui/CostValue'
import { CreditValue } from '@/components/ui/CreditValue'
import { canSeePrice } from '@/utils/money'
import { useAuth } from '@/context/AuthContext'
import { useWorkspace } from '@/context/WorkspaceContext'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'

// Which scope ran out — drives the chip label only.
function scopeKey(scope) {
  if (scope === 'team') return 'budgetExceeded.scopeTeam'
  if (scope === 'company') return 'budgetExceeded.scopeCompany'
  if (scope === 'holding') return 'budgetExceeded.scopeHolding'
  return 'budgetExceeded.scopeUser'
}

/**
 * BudgetExceededModal — HARD block surfaced when a request is refused by the
 * backend with HTTP 402. There is no "send anyway": a budget/credit ceiling is
 * enforced, not advisory, so the only action is to close and acknowledge.
 *
 * Announced as an `alertdialog` (this is a refusal the user must act on),
 * mirroring DLPViolationModal's `block` posture.
 *
 * @param {object}  props
 * @param {boolean} props.isOpen
 * @param {() => void} props.onClose
 * @param {'user'|'team'|'company'|'holding'} [props.scope='team']
 *   Which level's ceiling was hit — drives the scope chip + copy.
 * @param {'budget_exceeded'|'insufficient_credits'} [props.code]
 *   `budget_exceeded` ⇒ a spend ceiling; `insufficient_credits` ⇒ prepaid pool
 *   drained. Selects the body copy.
 * @param {number|null} [props.remaining] Remaining headroom in USD ($) — shown to
 *   price viewers only (admin / team-workspace owner). Row hidden when null.
 * @param {number|null} [props.limit]     The USD ceiling that was hit — price
 *   viewers only. Row hidden when null.
 * @param {number|null} [props.remainingCredits] Remaining headroom in Polymind
 *   Credits — the user-safe figure shown to everyone else. Row hidden when null.
 * @param {number|null} [props.limitCredits]     The credit ceiling that was hit —
 *   user-safe. Row hidden when null.
 *
 * A normal user must NEVER see a $ figure here: the `$` rows render only when
 * `canSeePrice` is true; otherwise we fall back to Polymind Credits, and when no
 * credit figures are present we drop the numeric block entirely (the message +
 * scope chip alone are still a complete refusal).
 */
export default function BudgetExceededModal({
  isOpen,
  onClose,
  scope = 'team',
  code,
  remaining = null,
  limit = null,
  remainingCredits = null,
  limitCredits = null,
}) {
  const { t } = useTranslation('billing')
  const { user } = useAuth()
  const { workspaces } = useWorkspace()
  const priceVisible = canSeePrice(user, workspaces)
  const isCredits = code === 'insufficient_credits'

  // Price viewers ($): admin or a team-workspace owner. Everyone else gets
  // credits. The two tiers are mutually exclusive so a $ value can never leak.
  const showPriceRemaining =
    priceVisible && remaining != null && Number.isFinite(Number(remaining))
  const showPriceLimit =
    priceVisible && limit != null && Number.isFinite(Number(limit))
  const showCreditRemaining =
    !priceVisible && remainingCredits != null && Number.isFinite(Number(remainingCredits))
  const showCreditLimit =
    !priceVisible && limitCredits != null && Number.isFinite(Number(limitCredits))
  const showNumericBlock =
    showPriceRemaining || showPriceLimit || showCreditRemaining || showCreditLimit

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose?.() }}>
      <DialogContent
        className="max-w-md"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="budget-exceeded-title"
        aria-describedby="budget-exceeded-body"
      >
        <DialogHeader>
          <DialogTitle id="budget-exceeded-title" className="flex items-center gap-2">
            <Ban className="h-4 w-4 shrink-0 text-err" aria-hidden="true" />
            {t('budgetExceeded.title')}
          </DialogTitle>
          <DialogDescription id="budget-exceeded-body">
            {isCredits
              ? t('budgetExceeded.bodyCredits')
              : t('budgetExceeded.bodyBudget')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {/* Scope chip — names whose ceiling stopped the request. */}
          <span className="inline-flex items-center gap-1.5 rounded-full border border-err/30 bg-err/10 px-2.5 py-1 text-[11px] font-medium text-err">
            {t(scopeKey(scope))}
          </span>

          {showNumericBlock && (
            <div className="space-y-1.5 rounded-md border border-fg-3/30 bg-bg-2/40 p-3 text-sm">
              {showPriceRemaining && (
                <div className="flex items-center justify-between">
                  <span className="text-fg-3">{t('budgetExceeded.remainingLabel')}</span>
                  <CostValue usd={Number(remaining)} className="font-medium text-fg-1" />
                </div>
              )}
              {showPriceLimit && (
                <div className="flex items-center justify-between">
                  <span className="text-fg-3">{t('budgetExceeded.limitLabel')}</span>
                  <CostValue usd={Number(limit)} className="font-medium text-fg-1" />
                </div>
              )}
              {showCreditRemaining && (
                <div className="flex items-center justify-between">
                  <span className="text-fg-3">{t('budgetExceeded.remainingCreditsLabel')}</span>
                  <CreditValue credits={Number(remainingCredits)} className="font-medium text-fg-1" />
                </div>
              )}
              {showCreditLimit && (
                <div className="flex items-center justify-between">
                  <span className="text-fg-3">{t('budgetExceeded.limitCreditsLabel')}</span>
                  <CreditValue credits={Number(limitCredits)} className="font-medium text-fg-1" />
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={() => onClose?.()}>
            {t('budgetExceeded.closeButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

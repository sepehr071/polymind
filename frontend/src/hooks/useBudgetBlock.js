import { useCallback, useMemo, useState, createElement } from 'react'
import BudgetExceededModal from '../components/billing/BudgetExceededModal'

/**
 * Shared HTTP-402 budget-block hook.
 *
 * NOT a pre-flight scan (unlike `useDlpConfirm`): this is a *catcher*. Spend
 * ceilings are reporting-able server-side but the actual refusal only comes back
 * on the request itself as a 402 `{ code, scope, remaining, limit }`. Each
 * surface that streams/POSTs an LLM request feeds the parsed error body to
 * `handleBudgetError`; if it's a budget/credit refusal the hook opens a hard
 * block modal and returns `true` so the caller can stop (don't fall through to
 * a generic error toast).
 *
 * Usage:
 *
 *   const { handleBudgetError, budgetModal } = useBudgetBlock()
 *   // in a stream/error handler:
 *   if (handleBudgetError(errorData)) return   // budget refusal — modal shown
 *   // ...otherwise handle the error normally
 *   // render in JSX:
 *   { budgetModal }
 *
 * @returns {{
 *   handleBudgetError: (data: any) => boolean,
 *   budgetModal: import('react').ReactElement,
 * }}
 */
export function useBudgetBlock() {
  // Holds the active refusal or null. Carries BOTH the $ figures (remaining /
  // limit — price viewers only) and the user-safe Polymind Credits figures
  // (remainingCredits / limitCredits) so the modal can pick per viewer tier.
  const [block, setBlock] = useState(null)

  const handleBudgetError = useCallback((data) => {
    const code = data?.code
    if (code !== 'budget_exceeded' && code !== 'insufficient_credits') {
      return false
    }
    setBlock({
      scope: data?.scope || 'team',
      code,
      // $ figures — surfaced to price viewers (admin / team owner) only.
      remaining: data?.remaining ?? null,
      limit: data?.limit ?? null,
      // Polymind Credits — the user-safe figures the modal shows to everyone else.
      remainingCredits: data?.remaining_credits ?? null,
      limitCredits: data?.limit_credits ?? null,
    })
    return true
  }, [])

  const handleClose = useCallback(() => {
    setBlock(null)
  }, [])

  // Pre-rendered element the page drops into its tree (mirrors useDlpConfirm).
  const budgetModal = useMemo(
    () =>
      createElement(BudgetExceededModal, {
        isOpen: !!block,
        onClose: handleClose,
        scope: block?.scope || 'team',
        code: block?.code,
        remaining: block?.remaining ?? null,
        limit: block?.limit ?? null,
        remainingCredits: block?.remainingCredits ?? null,
        limitCredits: block?.limitCredits ?? null,
      }),
    [block, handleClose],
  )

  return { handleBudgetError, budgetModal }
}

export default useBudgetBlock

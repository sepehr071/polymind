import api from './api'

/**
 * Billing API client — usage aggregations + manual credit ledger.
 *
 * - `getUsage(wid, { start, end })` returns the multi-axis spend response
 *   (`by_user`, `by_project`, `by_model`, `daily`, `totals`, `window`).
 * - `addCredits(wid, { amountUsd, type, note })` appends a manual ledger
 *   entry (owner-only on the backend).
 * - `getLedger(wid, { limit, skip })` returns paginated ledger entries
 *   plus the materialized `total_credits_usd` sum.
 */
export const billingService = {
  getUsage: (wid, { start, end } = {}) => {
    const params = {}
    if (start) params.start = start
    if (end) params.end = end
    return api
      .get(`/workspaces/${wid}/billing/usage`, { params })
      .then((r) => r.data)
  },
  addCredits: (wid, { amountUsd, type = 'top_up', note = '' } = {}) =>
    api
      .post(`/workspaces/${wid}/billing/credits`, {
        amount_usd: amountUsd,
        type,
        note,
      })
      .then((r) => r.data),
  getLedger: (wid, { limit = 100, skip = 0 } = {}) =>
    api
      .get(`/workspaces/${wid}/billing/ledger`, { params: { limit, skip } })
      .then((r) => r.data),
}

export default billingService

import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'

/**
 * react-query wrapper over the unified P1 analytics endpoint
 *   GET /api/{tier}/analytics/usage?scope=&id=&granularity=&from=&to=&breakdown=
 * where `tier` is 'admin' (the only tier now — the platform dashboard was
 * folded into the super-admin /admin shell). The `tier` param is retained for
 * the URL shape; admin pages pass `tier:'admin'`.
 *
 * Calls the shared axios `api` instance directly (its baseURL already ends in
 * `/api`, so the path is `/admin/...`). Returns the raw
 * envelope unchanged — components read `series`/`totals`/`deltas`/`breakdown`/
 * `cost_visible` (NEVER `response_model`-shaped; the backend returns the legacy
 * dict verbatim).
 *
 * GOTCHA (document, do not "optimize"): `active_users` is a distinct-user count
 * and is NOT summable across buckets — the window total `totals.active_users`
 * is computed server-side over the whole window, so never derive it by summing
 * `series[].active_users` in the UI.
 *
 * @param {Object}  params
 * @param {'admin'} params.tier
 * @param {'holding'|'company'|'team'|'user'} params.scope
 * @param {string|null} [params.id]            workspace/project/user UUID (null for holding)
 * @param {'day'|'week'|'month'} [params.granularity]
 * @param {string} [params.from]               ISO YYYY-MM-DD
 * @param {string} [params.to]                 ISO YYYY-MM-DD
 * @param {string} [params.breakdown]          e.g. 'model'
 * @param {boolean} [params.enabled]           gate the query
 * @returns {import('@tanstack/react-query').UseQueryResult}
 */
export function useAnalytics({
  tier,
  scope,
  id = null,
  granularity = 'day',
  from,
  to,
  breakdown,
  enabled = true,
} = {}) {
  const params = { scope, granularity }
  if (id) params.id = id
  if (from) params.from = from
  if (to) params.to = to
  if (breakdown) params.breakdown = breakdown

  return useQuery({
    // tier + every param participates in the cache key so a scope/range change
    // is a distinct entry (and a drilldown doesn't show a parent's cached data).
    queryKey: ['analytics-usage', tier, scope, id, granularity, from, to, breakdown],
    queryFn: async () => {
      const res = await api.get(`/${tier}/analytics/usage`, { params })
      return res.data
    },
    enabled: Boolean(enabled && tier && scope),
    staleTime: 60 * 1000, // 60s — cached per the spec; analytics is read-only
    refetchOnWindowFocus: false,
    placeholderData: (prev) => prev, // keep prior data mounted across range changes
  })
}

export default useAnalytics

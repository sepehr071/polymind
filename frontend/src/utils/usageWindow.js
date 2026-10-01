/**
 * Personal-usage window + request tally. Dashboard snapshot and settings
 * Usage tab MUST share this so they hit the same React Query key and the
 * same COUNT(*) definition.
 *
 * Request = COUNT(*) of usage_logs in the window (one billed LLM completion
 * per `_record_usage` row). Excludes platform-internal features
 * `content_safety` and `auto_title` (DLP smart-scan / auto-title — not a
 * user send). In-flight retries that never record, and local-ai (no
 * usage_logs), are not counted.
 */

export function localIsoDate(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** Local calendar month: 1st → today (inclusive). */
export function calendarMonthRange(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return {
    from: `${d.getFullYear()}-${p(d.getMonth() + 1)}-01`,
    to: localIsoDate(d),
  }
}

/** Backend `/usage/me` timestamps. Keep `.000Z` — parser accepts it. */
export function toApiWindow({ from, to }) {
  return {
    from: `${from}T00:00:00.000Z`,
    to: `${to}T23:59:59.999Z`,
  }
}

export function isCalendarMonthRange(from, to, now = new Date()) {
  const m = calendarMonthRange(now)
  return from === m.from && to === m.to
}

export const INTERNAL_USAGE_FEATURES = new Set(['content_safety', 'auto_title'])

export function sumUsageRequests(rows, { excludeInternal = true } = {}) {
  let n = 0
  for (const r of rows || []) {
    if (excludeInternal && INTERNAL_USAGE_FEATURES.has(r.key)) continue
    n += Number(r.count) || 0
  }
  return n
}

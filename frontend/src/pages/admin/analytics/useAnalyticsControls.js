import { useCallback, useEffect, useMemo, useState } from 'react'

/**
 * Shared controls state for every admin analytics dashboard: the
 * `GranularityRangePicker` value ({granularity, from, to}) plus the active
 * `metric` for the time-series toggle. Defaults to a trailing 30-day daily
 * window, and persists the user's preference (granularity + active metric, NOT
 * the absolute dates — those default fresh each visit) to localStorage so the
 * choice sticks across the drilldown tree.
 *
 * Per the P3 spec: persisted key `admin-analytics-prefs`.
 */
const PREFS_KEY = 'admin-analytics-prefs'
const DEFAULT_GRANULARITY = 'day'
const DEFAULT_WINDOW_DAYS = 30
const DEFAULT_METRIC = 'cost'

/** YYYY-MM-DD for a Date (local — matches the date input + backend window). */
function isoDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function defaultWindow() {
  const to = new Date()
  const from = new Date()
  from.setDate(from.getDate() - DEFAULT_WINDOW_DAYS)
  return { from: isoDate(from), to: isoDate(to) }
}

function readPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

/**
 * @param {object} [opts]
 * @param {boolean} [opts.costVisible]  when false, force `metric` off 'cost'
 * @returns controls bundle for the analytics scaffold
 */
export function useAnalyticsControls({ costVisible = true } = {}) {
  const prefs = useMemo(readPrefs, [])

  const [range, setRange] = useState(() => {
    const win = defaultWindow()
    return {
      granularity:
        prefs.granularity === 'week' || prefs.granularity === 'month'
          ? prefs.granularity
          : DEFAULT_GRANULARITY,
      from: win.from,
      to: win.to,
    }
  })

  const [metric, setMetric] = useState(() => {
    const saved = prefs.metric
    const valid = ['cost', 'calls', 'tokens', 'active_users']
    return valid.includes(saved) ? saved : DEFAULT_METRIC
  })

  // Cost masked → never sit on the (now-empty) cost metric.
  useEffect(() => {
    if (!costVisible && metric === 'cost') setMetric('calls')
  }, [costVisible, metric])

  // Persist preference (granularity + metric only) whenever either changes.
  useEffect(() => {
    try {
      localStorage.setItem(
        PREFS_KEY,
        JSON.stringify({ granularity: range.granularity, metric }),
      )
    } catch {
      /* private mode — ignore */
    }
  }, [range.granularity, metric])

  const onRangeChange = useCallback((next) => setRange(next), [])

  return { range, onRangeChange, metric, setMetric }
}

export default useAnalyticsControls

import { DollarSign, MessageSquare, Cpu, Users } from 'lucide-react'
import { fmtNumber, fmtCurrency } from '@/utils/persianLocale'

/**
 * Single source of truth for the four analytics metrics shared across every
 * admin dashboard: the StatTile row, the time-series toggle, and the breakdown
 * charts all read from here so labels / formatters / colors / trend-direction
 * never drift.
 *
 *  - `i18nKey`         → `analytics:metrics.<key>`
 *  - `format(v)`       → display string (currency for cost, grouped int else)
 *  - `colorIndex`      → `--chart-N` ramp slot for the series + spark
 *  - `deltaDirection`  → StatTile color semantics (active users up = good;
 *                        cost/calls/tokens stay neutral — a rise isn't "bad")
 *  - `costSensitive`   → hidden / disabled when `cost_visible === false`
 */
export const METRICS = [
  {
    key: 'cost',
    i18nKey: 'cost',
    icon: DollarSign,
    colorIndex: 1,
    deltaDirection: 'neutral',
    costSensitive: true,
    format: (v) => (v == null ? '—' : fmtCurrency(Number(v) || 0)),
  },
  {
    key: 'calls',
    i18nKey: 'calls',
    icon: MessageSquare,
    colorIndex: 2,
    deltaDirection: 'neutral',
    costSensitive: false,
    format: (v) => fmtNumber(Number(v) || 0),
  },
  {
    key: 'tokens',
    i18nKey: 'tokens',
    icon: Cpu,
    colorIndex: 3,
    deltaDirection: 'neutral',
    costSensitive: false,
    format: (v) => fmtNumber(Number(v) || 0),
  },
  {
    key: 'active_users',
    i18nKey: 'activeUsers',
    icon: Users,
    colorIndex: 4,
    deltaDirection: 'up-good',
    costSensitive: false,
    format: (v) => fmtNumber(Number(v) || 0),
  },
]

export const METRIC_BY_KEY = Object.fromEntries(METRICS.map((m) => [m.key, m]))

/**
 * Envelope `deltas[metric].pct` is a PERCENTAGE (e.g. 12.5 = +12.5%) or null;
 * StatTile wants a fractional change (0.125). Convert, preserving null.
 */
export function deltaFraction(pct) {
  if (pct == null || !Number.isFinite(Number(pct))) return null
  return Number(pct) / 100
}

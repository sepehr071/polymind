import { cn } from '@/lib/utils'

/**
 * LimitRow — labeled progress row for budgets/limits (budget-vs-actual bar).
 *
 * These rows are ADVISORY: budgets/caps in this app are reporting-only and are
 * never enforced at call time. So an over-target row reads as an AMBER "above
 * target" signal, NOT an alarming red breach. Pass `overTone="error"` only for a
 * genuinely hard, blocking limit (none today).
 *
 * @param {string} label
 * @param {number} used
 * @param {number} cap
 * @param {string} unit  prefix unit (e.g. '$', '€'). Default '$'. Use '' for token counts etc.
 * @param {(n:number)=>React.ReactNode} [valueFormatter]
 *   Renders `used`/`cap` (e.g. localized `fmtCurrency`). When supplied it owns
 *   the whole figure, so `unit` is ignored. Falls back to the plain en-US
 *   number + `unit` prefix when omitted.
 * @param {boolean} [over]  Force the over-limit treatment (amber fill + badge),
 *   independent of the threshold colouring. Use for an authoritative
 *   server-computed over-target flag.
 * @param {'warn'|'error'} [overTone='warn']  Colour family for the over-target
 *   state. Defaults to amber `warn` (advisory); `error` is reserved for a hard
 *   enforced limit.
 * @param {React.ReactNode} [overBadge]  Optional label for the over-target badge
 *   (e.g. "above target"). Omit for a bare marker.
 * @param {React.ReactNode} [note]  Persistent quiet sub-line under the bar
 *   (e.g. "tracking only — not enforced").
 * @param {React.ReactNode} [trailing]  Optional node rendered after the figure
 *   (e.g. a "% used" pill).
 * @param {string} className
 */
export default function LimitRow({
  label,
  used = 0,
  cap = 0,
  unit = '$',
  valueFormatter,
  over = false,
  overTone = 'warn',
  overBadge,
  note,
  trailing,
  className,
}) {
  const safeCap = cap > 0 ? cap : 1
  const rawPct = (used / safeCap) * 100
  const pct = Math.min(100, rawPct)
  const breached = over || rawPct >= 100
  const overColor = overTone === 'error' ? 'err' : 'warn'
  // Static class literals only — Tailwind JIT can't see a `bg-${x}` template.
  // Spec P2-05: budget bar uses a GRADIENT fill (on-track = accent; warm /
  // breached escalate to amber / red).
  const fillCls = breached
    ? overColor === 'err'
      ? 'bg-gradient-to-r from-err/80 to-err'
      : 'bg-gradient-to-r from-warn/80 to-warn'
    : rawPct > 60
      ? 'bg-gradient-to-r from-warn/80 to-warn'
      : 'bg-gradient-to-r from-accent/70 to-accent'

  const fmt = (n) => {
    if (valueFormatter) return valueFormatter(n)
    if (typeof n !== 'number') return n
    return `${unit}${n.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
  }

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-[12.5px] text-fg-1">
          {label}
          {breached && (
            <span
              className={cn(
                'inline-flex items-center rounded-full border px-1.5 py-px text-[10px] font-medium',
                overColor === 'err'
                  ? 'bg-err/15 border-err/30 text-err'
                  : 'bg-warn/15 border-warn/30 text-warn',
              )}
            >
              {overBadge || '!'}
            </span>
          )}
        </span>
        <span className="flex items-center gap-2 font-mono text-[11px] text-fg-3 tabular-nums">
          <span className={breached ? (overColor === 'err' ? 'text-err' : 'text-warn') : undefined}>
            {fmt(used)}
          </span>
          <span aria-hidden>/</span>
          <span>{fmt(cap)}</span>
          {trailing}
        </span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-bg-3">
        <div
          className={cn('h-full rounded-full transition-[width] duration-200', fillCls)}
          style={{ width: `${pct}%` }}
        />
      </div>
      {note && <span className="text-[10.5px] text-fg-4">{note}</span>}
    </div>
  )
}

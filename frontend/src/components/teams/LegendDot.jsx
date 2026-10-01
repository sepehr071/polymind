import { cn } from '@/lib/utils'

/**
 * LegendDot — small chart legend chip.
 *
 * @param {string} color  CSS color (hex, hsl, var(--token)).
 * @param {React.ReactNode} label
 * @param {React.ReactNode} value  Optional trailing value (e.g. '$12.40').
 * @param {string} className
 */
export default function LegendDot({ color, label, value, className }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <span
        aria-hidden
        className="h-2 w-2 rounded-sm"
        style={{ background: color }}
      />
      <span className="text-[12.5px] text-fg-2">{label}</span>
      {value != null && (
        <span className="text-[11px] text-fg-3">{value}</span>
      )}
    </span>
  )
}

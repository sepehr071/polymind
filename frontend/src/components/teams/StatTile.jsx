import { cn } from '@/lib/utils'
import { solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'

/**
 * StatTile — solid labeled stat tile. Big-number content on a panel surface.
 *
 * @param {string} label
 * @param {React.ReactNode} value
 * @param {React.ReactNode} hint
 * @param {string} [accent]  Deprecated — accepted for back-compat, no longer
 *   renders a decorative halo (not in the stat-tile spec).
 * @param {string} className
 */
// eslint-disable-next-line no-unused-vars
export default function StatTile({ label, value, hint, accent, className }) {
  return (
    <div
      className={cn('rounded-xl p-4', className)}
      style={solidPanelSx({ radius: RADII.surface })}
    >
      <div className="text-[12px] font-medium text-fg-3">{label}</div>
      <div
        className="mt-1.5 font-extrabold text-fg-0"
        style={{ fontSize: 24, letterSpacing: '-0.01em', lineHeight: 1.1 }}
      >
        {value}
      </div>
      {hint && <div className="mt-2 text-[11px] text-fg-3">{hint}</div>}
    </div>
  )
}

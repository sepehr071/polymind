import { RADII } from './tokens'

/**
 * Surface helpers — Minimal UI style (NO frost/blur by default).
 *
 * Historical names kept so call sites don't explode:
 * - glassSx / GLASS_CLASS → now solid paper + card shadow (quiet legacy alias)
 * - solidPanelSx → canonical content panel
 * - SOLID_SURFACE_CLASS → Tailwind solid floating panels
 */

/** @deprecated use solidPanelSx — kept as alias for chrome that was glassed */
export const glassSx = ({ strong = false, radius = RADII.surface } = {}) =>
  solidPanelSx({ radius, elevated: true })

export const GLASS_CLASS = 'minimal-surface'

/** Solid content panel — Minimal card DNA (shadow via CSS var for light/dark). */
export const solidPanelSx = ({ radius = RADII.surface, elevated = true } = {}) => ({
  backgroundColor: 'var(--mui-palette-background-paper, #fff)',
  border: 'none',
  boxShadow: elevated
    ? 'var(--card-shadow, 0 0 2px 0 rgba(100,116,139,0.2), 0 12px 24px -4px rgba(100,116,139,0.12))'
    : 'none',
  borderRadius: `${radius}px`,
})

/** Tailwind classes for solid floating panels (menus, select, toast). */
export const SOLID_SURFACE_CLASS =
  'bg-background-secondary border-0 shadow-[0_0_2px_0_rgba(100,116,139,0.24),-20px_20px_40px_-4px_rgba(100,116,139,0.24)]'

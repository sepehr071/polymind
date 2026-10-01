/**
 * Landing design contract — warm dark luxury.
 * Single source of truth for the landing's surface recipes, aurora layers and
 * motion grammar.
 *
 * Glass budget: LANDING_GLASS may appear on exactly two surfaces page-wide
 * (scrolled Navbar + ProductShowcase window). Everything else uses
 * LANDING_SURFACE — solid tint, no backdrop-filter.
 */

/* Solid tinted card. Hover: border brightens + warm lamp glow.
   NO position class on purpose — `relative` here silently overrides `absolute`
   on consumers (.relative wins in Tailwind's emit order). Positioned consumers
   bring their own position class. */
export const LANDING_SURFACE =
  'rounded-2xl border border-white/[0.08] bg-white/[0.03] ' +
  'transition-[border-color,box-shadow] duration-500 ' +
  'hover:border-white/[0.16] hover:shadow-[0_0_48px_-12px_hsl(var(--landing-warm)/0.18)]'

/* Frosted glass — the 2 hero moments ONLY. Position-free, same reason. */
export const LANDING_GLASS =
  'rounded-2xl border border-white/[0.10] bg-white/[0.05] ' +
  'backdrop-blur-xl shadow-[0_16px_56px_-16px_rgba(0,0,0,0.7)]'

/* Touch-device fallback for LANDING_GLASS: same frame, NO backdrop-filter (the
   per-frame backdrop raster is the mobile killer). A more opaque tinted fill
   stands in for the lensing so it reads near-identical without the cost. Swap
   in via useCoarsePointer() on the two glass surfaces. */
export const LANDING_GLASS_SOLID =
  'rounded-2xl border border-white/[0.10] bg-[hsl(var(--bg-1)/0.92)] ' +
  'shadow-[0_16px_56px_-16px_rgba(0,0,0,0.7)]'

/* Aurora mesh layers — inline-style objects for aria-hidden background divs.
   Radial blobs: sky top-start, warm amber lamp pocket, teal depth. RTL-safe
   (percentages read fine mirrored; warmth placement is decorative). */
const blob = (size, x, y, color, alpha) =>
  `radial-gradient(${size} ${size} at ${x} ${y}, hsl(${color} / ${alpha}), transparent 58%)`

export const AURORA_HERO = {
  backgroundImage: [
    blob('46rem', '14%', '12%', 'var(--accent)', 0.16),
    blob('38rem', '78%', '30%', 'var(--landing-warm)', 0.1),
    blob('44rem', '60%', '96%', 'var(--teal)', 0.08),
  ].join(', '),
}

export const AURORA_MID = {
  backgroundImage: [
    blob('40rem', '85%', '8%', 'var(--accent)', 0.1),
    blob('36rem', '12%', '85%', 'var(--landing-warm)', 0.08),
  ].join(', '),
}

export const AURORA_CTA = {
  backgroundImage: [
    blob('42rem', '50%', '18%', 'var(--landing-warm)', 0.12),
    blob('40rem', '12%', '88%', 'var(--accent)', 0.1),
    blob('36rem', '88%', '80%', 'var(--teal)', 0.07),
  ].join(', '),
}

/* Type recipes. FA never uppercases/tracks — pick per isRTL. */
export const EYEBROW_EN =
  'text-xs font-medium uppercase tracking-[0.2em] text-foreground-tertiary'
export const EYEBROW_FA = 'text-sm font-medium text-foreground-tertiary'

export const H2_CLASS = 'text-[clamp(2rem,4vw,3.5rem)] font-bold leading-tight'

/* Motion grammar — the only entrance curve + shared reveal. */
export const easeOutExpo = [0.16, 1, 0.3, 1]

export const revealVariants = {
  hidden: { opacity: 0, y: 24, filter: 'blur(8px)' },
  visible: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: 0.7, ease: easeOutExpo },
  },
}

export const viewportOnce = { once: true, margin: '-80px' }

import { cn } from '@/utils/cn'

/**
 * IconTile — small tinted tile behind a lucide glyph (macOS System Settings
 * style). The tone system is the app's icon-wayfinding palette: one hue per
 * sidebar zone (work=sky, studio=amber, library=emerald), `accent` for brand
 * moments, `neutral` for low-frequency chrome (settings, quick actions).
 *
 * Class strings are STATIC LITERALS — Tailwind's JIT scans source verbatim,
 * template-built class names silently purge. NOTE: the `violet`/`pink`/`teal`
 * Tailwind scales are overridden by flat tokens in tailwind.config.js (no
 * -500 shades) — keep tones on intact default scales (sky/amber/emerald/rose).
 */
// Soft-3D premium tiles: a vertical gradient (lighter top → tone bottom) reads
// as a lit, slightly-raised chip rather than a flat tint. The depth — a 1px top
// highlight + a soft drop shadow — lives on the shared base (tone-independent);
// each tone only swaps the gradient stops + inset ring color. Active = brighter
// gradient + stronger ring (chip "lights up"). Classes stay STATIC LITERALS so
// Tailwind's JIT can see them.
const TONES = {
  sky: {
    tile: 'bg-gradient-to-b from-sky-400/25 to-sky-500/[0.06] ring-sky-500/20 text-sky-600 dark:from-sky-400/20 dark:to-sky-400/[0.04] dark:ring-sky-400/20 dark:text-sky-400',
    tileActive: 'bg-gradient-to-b from-sky-400/45 to-sky-500/15 ring-sky-500/40 text-sky-700 dark:from-sky-400/35 dark:to-sky-400/10 dark:ring-sky-400/40 dark:text-sky-200',
    glyph: 'text-sky-600 dark:text-sky-400',
    rowActive: 'bg-sky-500/10 text-sky-700 ring-1 ring-inset ring-sky-500/25 dark:bg-sky-400/10 dark:text-sky-300 dark:ring-sky-400/25',
  },
  amber: {
    tile: 'bg-gradient-to-b from-amber-400/25 to-amber-500/[0.06] ring-amber-500/20 text-amber-600 dark:from-amber-400/20 dark:to-amber-400/[0.04] dark:ring-amber-400/20 dark:text-amber-400',
    tileActive: 'bg-gradient-to-b from-amber-400/45 to-amber-500/15 ring-amber-500/40 text-amber-700 dark:from-amber-400/35 dark:to-amber-400/10 dark:ring-amber-400/40 dark:text-amber-200',
    glyph: 'text-amber-600 dark:text-amber-400',
    rowActive: 'bg-amber-500/10 text-amber-700 ring-1 ring-inset ring-amber-500/25 dark:bg-amber-400/10 dark:text-amber-300 dark:ring-amber-400/25',
  },
  emerald: {
    tile: 'bg-gradient-to-b from-emerald-400/25 to-emerald-500/[0.06] ring-emerald-500/20 text-emerald-600 dark:from-emerald-400/20 dark:to-emerald-400/[0.04] dark:ring-emerald-400/20 dark:text-emerald-400',
    tileActive: 'bg-gradient-to-b from-emerald-400/45 to-emerald-500/15 ring-emerald-500/40 text-emerald-700 dark:from-emerald-400/35 dark:to-emerald-400/10 dark:ring-emerald-400/40 dark:text-emerald-200',
    glyph: 'text-emerald-600 dark:text-emerald-400',
    rowActive: 'bg-emerald-500/10 text-emerald-700 ring-1 ring-inset ring-emerald-500/25 dark:bg-emerald-400/10 dark:text-emerald-300 dark:ring-emerald-400/25',
  },
  rose: {
    tile: 'bg-gradient-to-b from-rose-400/25 to-rose-500/[0.06] ring-rose-500/20 text-rose-600 dark:from-rose-400/20 dark:to-rose-400/[0.04] dark:ring-rose-400/20 dark:text-rose-400',
    tileActive: 'bg-gradient-to-b from-rose-400/45 to-rose-500/15 ring-rose-500/40 text-rose-700 dark:from-rose-400/35 dark:to-rose-400/10 dark:ring-rose-400/40 dark:text-rose-200',
    glyph: 'text-rose-600 dark:text-rose-400',
    rowActive: 'bg-rose-500/10 text-rose-700 ring-1 ring-inset ring-rose-500/25 dark:bg-rose-400/10 dark:text-rose-300 dark:ring-rose-400/25',
  },
  accent: {
    tile: 'bg-gradient-to-b from-accent/20 to-accent/[0.04] ring-accent/20 text-accent',
    tileActive: 'bg-gradient-to-b from-accent/35 to-accent/10 ring-accent/40 text-accent',
    glyph: 'text-accent',
    rowActive: '',
  },
  neutral: {
    tile: 'bg-gradient-to-b from-foreground/[0.08] to-foreground/[0.02] ring-foreground/10 text-foreground-secondary',
    tileActive: 'bg-gradient-to-b from-foreground/[0.15] to-foreground/[0.05] ring-foreground/20 text-foreground',
    glyph: 'text-foreground-secondary',
    rowActive: '',
  },
}

const SIZES = {
  sm: { tile: 'h-6 w-6 rounded-md', icon: 'h-3.5 w-3.5' },
  md: { tile: 'h-7 w-7 rounded-lg', icon: 'h-4 w-4' },
  lg: { tile: 'h-9 w-9 rounded-xl', icon: 'h-5 w-5' },
  // xl = the canonical PAGE-HEADER tile (Consistent UI System spec: 40px, radius
  // 13, 20px glyph). Use only in PageHeader-class contexts.
  xl: { tile: 'h-10 w-10 rounded-[13px]', icon: 'h-5 w-5' },
}

export function toneClasses(tone) {
  return TONES[tone] || TONES.neutral
}

export function IconTile({ icon: Icon, tone = 'neutral', size = 'md', active = false, className, iconClassName }) {
  if (!Icon) return null
  const t = toneClasses(tone)
  const s = SIZES[size] || SIZES.md
  return (
    <span
      className={cn(
        'relative grid shrink-0 place-items-center ring-1 ring-inset transition-all duration-200',
        // depth: 1px top highlight + soft drop shadow (tone-independent)
        'shadow-[inset_0_1px_0_0_rgb(255_255_255_/_0.30),0_1px_2px_-1px_rgb(15_23_42_/_0.18)]',
        'dark:shadow-[inset_0_1px_0_0_rgb(255_255_255_/_0.08),0_1px_2px_-1px_rgb(0_0_0_/_0.55)]',
        s.tile,
        active ? t.tileActive : t.tile,
        className,
      )}
    >
      <Icon className={cn(s.icon, 'drop-shadow-[0_1px_1px_rgb(0_0_0_/_0.12)]', iconClassName)} />
    </span>
  )
}

export default IconTile

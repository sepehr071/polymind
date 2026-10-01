import { cn } from '@/lib/utils'

/**
 * PageShell — canonical scroll-page scaffold for routed content pages.
 *
 * After the fixed sidebar was removed (2026-06-16) every page owns the full
 * viewport width, so "how wide is a page" became a single decision instead of a
 * per-page magic number. This primitive encodes that decision as a named width
 * TOKEN — pages opt into a semantic lane, not a hand-copied `max-w-*`.
 *
 *   reading  768px  conversation / prose lanes (chat-like). Capped ON PURPOSE.
 *   form     768px  linear settings / provisioning forms (label+input stacks).
 *   standard 1024px sparse launchers, short lists, mixed content (default).
 *   wide     1280px card grids, libraries, the hub.
 *   dense    1920px data tables, analytics, dense admin surfaces.
 *   full     —      full-bleed; no cap (rarely needed — most full-bleed pages
 *                   manage their own flex/height shell and skip PageShell).
 *
 * `reading` and `form` resolve to the same px but stay semantically distinct so
 * intent is self-documenting and the two can diverge later.
 *
 * Vertical rhythm is fixed at space-y-6 — direct children are the page's stacked
 * sections (header, cards, tables). Pass extra layout via className.
 *
 * @param {('reading'|'form'|'standard'|'wide'|'dense'|'full')} [width='standard']
 * @param {boolean} [wide]      back-compat alias for width="wide" (legacy callers)
 * @param {string}  [className] extra classes merged onto the inner column
 * @param {React.ReactNode} children
 */
const WIDTH_CLASS = {
  reading: 'max-w-3xl',
  form: 'max-w-3xl',
  standard: 'max-w-5xl',
  wide: 'max-w-7xl',
  dense: 'max-w-[120rem]',
  full: 'max-w-none',
}

export default function PageShell({ width, wide = false, className, children }) {
  const token = width ?? (wide ? 'wide' : 'standard')
  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className={cn(WIDTH_CLASS[token] ?? WIDTH_CLASS.standard, 'mx-auto space-y-6', className)}>
        {children}
      </div>
    </div>
  )
}

// Canonical alias — `PageContainer` is the intent-revealing name going forward;
// `PageShell` is kept so existing imports keep working.
export { PageShell as PageContainer }
export { PageShell }

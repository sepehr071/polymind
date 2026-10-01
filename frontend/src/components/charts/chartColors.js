/**
 * Analytics chart palette helpers (DOM-side).
 *
 * The six series colors live as space-separated HSL triplets in index.css
 * (`--chart-1` … `--chart-6`, light + dark). DOM consumers want a real CSS
 * color string, so these helpers wrap the token as `hsl(var(--chart-N))` — a
 * bare `var(--chart-N)` is an invalid color and silently renders nothing.
 *
 * NOTE: the ECharts kit components do NOT use these — the canvas can't read CSS
 * vars, so they RESOLVE the tokens to literal colors via `useEchartTheme`.
 * These remain for any DOM-side swatch/legend that wants the same ramp.
 */

export const CHART_SERIES_COUNT = 6

/** `hsl(var(--chart-N))` for a 1-based index, wrapping past 6. */
export function chartColor(index) {
  const n = (((index - 1) % CHART_SERIES_COUNT) + CHART_SERIES_COUNT) % CHART_SERIES_COUNT
  return `hsl(var(--chart-${n + 1}))`
}

/** Same color at a given alpha — for area fills / muted bars. */
export function chartColorAlpha(index, alpha) {
  const n = (((index - 1) % CHART_SERIES_COUNT) + CHART_SERIES_COUNT) % CHART_SERIES_COUNT
  return `hsl(var(--chart-${n + 1}) / ${alpha})`
}

/** Full ordered ramp, 1-based color strings. */
export const CHART_COLORS = Array.from({ length: CHART_SERIES_COUNT }, (_, i) => chartColor(i + 1))

// Shared axis / grid styling so every chart matches the established
// AdminDashboard / HoldingOverview look without copy-pasting the strings.
export const AXIS_STROKE = 'hsl(var(--foreground-tertiary))'
export const GRID_STROKE = 'hsl(var(--border) / 0.5)'
export const AXIS_FONT_SIZE = 11

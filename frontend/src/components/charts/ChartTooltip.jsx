import { echarts } from './echartsCore'

/**
 * One themed tooltip for the whole analytics chart kit — kills the per-file
 * `contentStyle` blobs that drifted across AdminDashboard / HoldingOverview.
 *
 * Previously a React component rendered via recharts' `content` prop. ECharts
 * tooltips are an HTML-string `formatter(params)`, so this is now a factory:
 * `buildTooltipFormatter(opts)` returns that callback, styled to match the old
 * `bg-background-elevated` card (a heading, a color swatch + label + tabular
 * value per series).
 *
 * Resolved theme colors are passed in (the canvas can't read CSS vars) via the
 * `theme` arg from `useEchartTheme`.
 *
 *   tooltip: {
 *     trigger: 'axis',
 *     formatter: buildTooltipFormatter({ formatters, labelKeys, labelFormatter, theme }),
 *   }
 *
 * @param {object}   opts
 * @param {Object<string,(v)=>string>} [opts.formatters]  seriesKey → value formatter
 * @param {Object<string,string>}      [opts.labelKeys]    seriesKey → display label
 * @param {(label)=>string}            [opts.labelFormatter] format the axis/category heading
 * @param {(v)=>string}                [opts.fallbackFormatter] default value formatter
 * @param {object}   opts.theme        resolved theme (tooltipBg, fgColor, fgSecondary, gridColor, fontFamily)
 * @returns {(params:object|object[]) => string} echarts tooltip.formatter
 */
const enc = echarts.format.encodeHTML

export function buildTooltipFormatter({
  formatters = {},
  labelKeys = {},
  labelFormatter,
  fallbackFormatter = (v) => v,
  theme = {},
} = {}) {
  const {
    tooltipBg = '#1f1f1f',
    fgColor = '#e5e5e5',
    fgSecondary = '#9ca3af',
    gridColor = 'rgba(148,163,184,0.25)',
    fontFamily = "'Vazirmatn',ui-sans-serif,system-ui,sans-serif",
  } = theme

  const wrap = (heading, rows) => {
    const head =
      heading != null && heading !== ''
        ? `<div style="margin-bottom:6px;font-weight:600;color:${fgColor}">${enc(String(heading))}</div>`
        : ''
    return (
      `<div style="border:1px solid ${gridColor};background:${tooltipBg};` +
      `border-radius:8px;padding:8px 12px;font-size:12px;font-family:${fontFamily};` +
      `box-shadow:0 8px 24px rgba(0,0,0,0.18)">${head}${rows}</div>`
    )
  }

  const lineFor = (color, key, name, value) => {
    const fmt = formatters[key] || fallbackFormatter
    const label = labelKeys[key] || name || key
    const swatch =
      `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;` +
      `flex-shrink:0;background:${color}"></span>`
    return (
      `<div style="display:flex;align-items:center;gap:8px;margin-top:2px">` +
      `${swatch}<span style="color:${fgSecondary}">${enc(String(label))}</span>` +
      `<span style="margin-inline-start:auto;font-variant-numeric:tabular-nums;` +
      `font-weight:500;color:${fgColor}">${enc(String(fmt(value)))}</span></div>`
    )
  }

  return (params) => {
    // axis trigger → array of series points at one category; item trigger → one.
    const arr = Array.isArray(params) ? params : [params]
    if (arr.length === 0) return ''

    const first = arr[0]
    const rawHeading = first?.axisValueLabel ?? first?.axisValue ?? first?.name
    const heading = labelFormatter ? labelFormatter(rawHeading) : rawHeading

    const rows = arr
      .map((p) => {
        // key precedence: explicit seriesId (set to the metric key) → seriesName.
        const key = p.seriesId || p.seriesName
        // value: cartesian series → value[1]/value; pie → value.
        const value = Array.isArray(p.value) ? p.value[p.value.length - 1] : p.value
        return lineFor(p.color, key, p.seriesName, value)
      })
      .join('')

    return wrap(heading, rows)
  }
}

export default buildTooltipFormatter
